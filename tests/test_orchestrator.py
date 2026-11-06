"""Task pipelines: real role-scoped MCP, mocked providers, temporary accounting."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from test_role_stdio import connection

from my_mcp_agent import accounting, ledger
from my_mcp_agent.authorization import RoleDispatcher
from my_mcp_agent.client import connect_stdio
from my_mcp_agent.orchestrator import TaskRunner
from my_mcp_agent.providers.base import (
    Message,
    ModelReply,
    PreparedRequest,
    ProviderConfig,
    ReviewDecision,
    ToolCall,
    Usage,
)
from my_mcp_agent.providers.http import HTTPModelAdapter
from my_mcp_agent.roles import RoleProfile, load_role


def provider_config(protocol="chat_completions", **changes):
    data = {
        "protocol": protocol,
        "model": "fake-model",
        "endpoint": "https://provider.invalid/chat",
        "supports_tools": True,
        "input_usd_per_million": "0.1",
        "output_usd_per_million": "0.2",
        "reservation_usd": "0.01",
    }
    return ProviderConfig.model_validate({**data, **changes})


def response(protocol, text="done", calls=()):
    if protocol == "chat_completions":
        return {
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "choices": [
                {
                    "finish_reason": "tool_calls" if calls else "stop",
                    "message": {
                        "content": text,
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": json.dumps(call.arguments),
                                },
                            }
                            for call in calls
                        ],
                    },
                }
            ],
        }
    return {
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 100,
        "eval_count": 20,
        "message": {
            "content": text,
            "tool_calls": [
                {"function": {"name": call.name, "arguments": call.arguments}}
                for call in calls
            ],
        },
    }


async def approve(context):
    return ReviewDecision(approved=True)


class ScriptedAdapter:
    def __init__(self, replies, **config):
        self.config = provider_config(**config)
        self.replies = iter(replies)
        self.sends = 0

    def prepare(self, messages: list[Message], tools: list[dict]):
        return PreparedRequest(payload={"turn": self.sends})

    async def send(self, request):
        self.sends += 1
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def reply(text="done", calls=(), output=1):
    return ModelReply(
        text=text, calls=calls, usage=Usage(input_tokens=1, output_tokens=output)
    )


class TaskRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="studio-pipeline-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, value in (
            ("LEDGER_DB_PATH", self.root / "ledger.db"),
            ("DAILY_BUDGET_USD", 1.0),
        ):
            override = patch.object(ledger, name, value)
            override.start()
            self.addCleanup(override.stop)

    async def test_both_provider_protocols_reuse_roles_and_mcp_tools(self):
        for protocol in ("chat_completions", "ollama"):
            with self.subTest(protocol=protocol):
                calls = 0

                def respond(request, protocol=protocol):
                    nonlocal calls
                    payload = json.loads(request.content)
                    self.assertNotIn(
                        "log_task_usage",
                        {tool["function"]["name"] for tool in payload["tools"]},
                    )
                    calls += 1
                    if calls == 1:
                        tool = ToolCall(
                            id="write",
                            name="write_file",
                            arguments={
                                "rel_path": f"{protocol}.md",
                                "content": "pipeline artifact",
                            },
                        )
                        return httpx.Response(
                            200, json=response(protocol, text="", calls=(tool,))
                        )
                    return httpx.Response(
                        200, json=response(protocol, text="Created and reviewed.")
                    )

                adapter = HTTPModelAdapter(
                    provider_config(protocol), httpx.MockTransport(respond)
                )
                async with connect_stdio(connection(self.root, "writer")) as session:
                    runner = TaskRunner(
                        adapter, RoleDispatcher(session, load_role("writer")), approve
                    )
                    result = await runner.run(
                        "TASK_PRIVATE_CONTENT create the requested artifact",
                        f"pipeline_{protocol}",
                    )
                self.assertEqual(result.status, "completed")
                self.assertEqual(result.steps, 2)
                self.assertEqual(
                    (self.root / f"game/{protocol}.md").read_text(), "pipeline artifact"
                )
                self.assertEqual(calls, 2)
                status = accounting.task_status(result.task_id)
                self.assertNotIn("TASK_PRIVATE_CONTENT", json.dumps(status))
                self.assertNotIn("pipeline artifact", json.dumps(status))
        self.assertEqual(ledger.get_budget_summary()["task_count"], 4)

    async def test_denied_tool_and_resource_requests_do_not_gain_permissions(self):
        adapter = ScriptedAdapter(
            [
                reply(
                    calls=(
                        ToolCall(
                            id="write",
                            name="write_file",
                            arguments={"rel_path": "bad.txt", "content": "bad"},
                        ),
                        ToolCall(
                            id="resource",
                            name="read_studio_resource",
                            arguments={"uri": "studio://telemetry/budget"},
                        ),
                    )
                ),
                reply("Requests were denied."),
            ]
        )
        async with connect_stdio(connection(self.root, "qa")) as session:
            result = await TaskRunner(
                adapter, RoleDispatcher(session, load_role("qa")), approve
            ).run("Review only", "denied")
        self.assertEqual(result.status, "completed")
        self.assertFalse((self.root / "game/bad.txt").exists())
        self.assertTrue(
            all(
                item["state"] == "failed"
                for item in accounting.task_status("denied")["tools"]
            )
        )

    async def test_budget_preflight_blocks_provider_call(self):
        adapter = ScriptedAdapter([reply()])
        with patch.object(ledger, "DAILY_BUDGET_USD", 0):
            async with connect_stdio(connection(self.root, "qa")) as session:
                result = await TaskRunner(
                    adapter, RoleDispatcher(session, load_role("qa"))
                ).run("Inspect", "blocked")
        self.assertEqual(result.status, "budget_blocked")
        self.assertEqual(adapter.sends, 0)

    async def test_provider_timeout_retains_hold_and_prevents_restart_replay(self):
        adapter = ScriptedAdapter([httpx.ReadTimeout("DO_NOT_LOG_EXCEPTION_SECRET")])
        async with connect_stdio(connection(self.root, "qa")) as session:
            runner = TaskRunner(adapter, RoleDispatcher(session, load_role("qa")))
            result = await runner.run("Inspect", "uncertain")
            self.assertEqual(result.status, "provider_uncertain")
            with self.assertRaises(accounting.ReplayError):
                await runner.run("Inspect", "uncertain")
        self.assertEqual(adapter.sends, 1)
        self.assertEqual(ledger.get_budget_summary()["reserved_usd"], "0.01")
        status = accounting.task_status("uncertain")
        self.assertEqual(status["requests"][0]["state"], "uncertain")
        self.assertNotIn("DO_NOT_LOG_EXCEPTION_SECRET", json.dumps(status))
        accounting.settle("uncertain:1", 1, 1, "0.001")
        self.assertEqual(ledger.get_budget_summary()["reserved_usd"], "0")

    async def test_step_limit_and_review_revision_loop(self):
        profile = RoleProfile.model_validate(
            {**load_role("qa").model_dump(), "max_steps": 2}
        )
        adapter = ScriptedAdapter([reply("draft"), reply("revised")])
        reviews = 0

        async def review(context):
            nonlocal reviews
            reviews += 1
            return ReviewDecision(
                approved=reviews == 2,
                feedback="Revise the draft." if reviews == 1 else "",
            )

        async with connect_stdio(connection(self.root, "qa")) as session:
            result = await TaskRunner(
                adapter, RoleDispatcher(session, profile), review
            ).run("Inspect", "revision")
        self.assertEqual(result.status, "completed")
        self.assertEqual(reviews, 2)
        self.assertIn(
            "revision_requested",
            {event["event"] for event in accounting.task_status("revision")["events"]},
        )
        adapter = ScriptedAdapter(
            [
                reply(
                    calls=(ToolCall(id=f"c{i}", name="workspace_ping", arguments={}),)
                )
                for i in range(2)
            ]
        )
        async with connect_stdio(connection(self.root, "qa")) as session:
            result = await TaskRunner(
                adapter, RoleDispatcher(session, profile), approve
            ).run("Inspect", "limited")
        self.assertEqual(result.status, "step_limit")
        self.assertEqual(adapter.sends, 2)

    async def test_cancellation_retains_uncertain_reservation(self):
        import asyncio

        started = asyncio.Event()
        adapter = ScriptedAdapter([])

        async def wait_forever(request):
            started.set()
            await asyncio.Event().wait()

        adapter.send = wait_forever
        async with connect_stdio(connection(self.root, "qa")) as session:
            runner = TaskRunner(adapter, RoleDispatcher(session, load_role("qa")))
            running = asyncio.create_task(runner.run("Inspect", "cancelled"))
            await asyncio.wait_for(started.wait(), 10)
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running
        status = accounting.task_status("cancelled")
        self.assertEqual(status["state"], "interrupted")
        self.assertEqual(status["requests"][0]["state"], "uncertain")
        self.assertEqual(ledger.get_budget_summary()["reserved_usd"], "0.01")

    async def test_approved_resource_is_available_through_checked_resource_tool(self):
        (self.root / "game").mkdir()
        (self.root / "game/GDD.md").write_text("approved project context")
        adapter = ScriptedAdapter(
            [
                reply(
                    calls=(
                        ToolCall(
                            id="memory",
                            name="read_studio_resource",
                            arguments={"uri": "studio://memory/architecture"},
                        ),
                    )
                ),
                reply("Reviewed architecture."),
            ]
        )
        async with connect_stdio(connection(self.root, "qa")) as session:
            result = await TaskRunner(
                adapter, RoleDispatcher(session, load_role("qa")), approve
            ).run("Inspect", "memory")
        self.assertEqual(result.status, "completed")
        self.assertEqual(
            accounting.task_status("memory")["tools"][0]["tool"], "read_studio_resource"
        )

    async def test_failed_execution_is_not_presented_as_successful_review_evidence(
        self,
    ):
        adapter = ScriptedAdapter(
            [
                reply(
                    calls=(
                        ToolCall(
                            id="test",
                            name="run_tests",
                            arguments={"test_target": "tests"},
                        ),
                    )
                ),
                reply("Tests failed; changes need review."),
            ]
        )
        seen = []

        async def reviewer(context):
            seen.append(context)
            return ReviewDecision(approved=True)

        from types import SimpleNamespace

        async with connect_stdio(connection(self.root, "qa")) as session:
            dispatcher = RoleDispatcher(session, load_role("qa"))
            dispatcher.call_tool = AsyncMock(
                return_value=SimpleNamespace(
                    is_error=False,
                    structured_content={
                        "passed": False,
                        "exit_code": 1,
                        "timed_out": False,
                    },
                    model_dump=lambda **kwargs: {
                        "is_error": False,
                        "structured_content": {"passed": False, "exit_code": 1},
                    },
                )
            )
            result = await TaskRunner(adapter, dispatcher, reviewer).run(
                "Test", "failed_checks"
            )
        self.assertEqual(result.status, "completed")
        self.assertNotIn("run_tests", seen[0].successful_tools)
        self.assertIn("run_tests", seen[0].failed_tools)
        self.assertEqual(
            accounting.task_status("failed_checks")["tools"][0]["state"], "failed"
        )

    async def test_no_reviewer_does_not_claim_work_is_approved(self):
        async with connect_stdio(connection(self.root, "qa")) as session:
            result = await TaskRunner(
                ScriptedAdapter([reply("candidate")]),
                RoleDispatcher(session, load_role("qa")),
            ).run("Inspect", "review_pending")
        self.assertEqual(result.status, "needs_review")
        self.assertEqual(result.answer, "candidate")

    async def test_uncertain_tool_side_effect_is_not_retried(self):
        tool = ToolCall(
            id="write-once",
            name="write_file",
            arguments={"rel_path": "once.md", "content": "written once"},
        )
        adapter = ScriptedAdapter([reply(calls=(tool,))])
        async with connect_stdio(connection(self.root, "writer")) as session:
            dispatcher = RoleDispatcher(session, load_role("writer"))
            original = dispatcher.call_tool

            async def lost_reply(name, arguments):
                await original(name, arguments)
                raise ConnectionError("simulated lost tool response")

            dispatcher.call_tool = AsyncMock(side_effect=lost_reply)
            result = await TaskRunner(adapter, dispatcher).run(
                "Write the note", "tool_uncertain"
            )
        self.assertEqual(result.status, "tool_uncertain")
        self.assertEqual((self.root / "game/once.md").read_text(), "written once")
        self.assertEqual(
            accounting.task_status("tool_uncertain")["tools"][0]["state"], "started"
        )
        self.assertEqual(adapter.sends, 1)

    async def test_overrun_and_duplicate_calls_stop_before_side_effects(self):
        call = ToolCall(
            id="same",
            name="write_file",
            arguments={"rel_path": "bad.md", "content": "bad"},
        )
        for task_id, adapter, expected in (
            (
                "overrun",
                ScriptedAdapter(
                    [reply(calls=(call,), output=1000)], reservation_usd="0.000001"
                ),
                "budget_overrun",
            ),
            ("duplicates", ScriptedAdapter([reply(calls=(call, call))]), "failed"),
        ):
            async with connect_stdio(connection(self.root, "writer")) as session:
                result = await TaskRunner(
                    adapter, RoleDispatcher(session, load_role("writer"))
                ).run("Write", task_id)
            self.assertEqual(result.status, expected)
            self.assertFalse((self.root / "game/bad.md").exists())
