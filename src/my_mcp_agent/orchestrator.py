"""Bounded provider-neutral task loop with trusted roles and durable accounting."""

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, Field

from my_mcp_agent import accounting
from my_mcp_agent.authorization import (
    RoleAccessDenied,
    RoleCallLimitError,
    RoleDispatcher,
)
from my_mcp_agent.client import StdioConnection, connect_stdio
from my_mcp_agent.providers.base import (
    Message,
    ModelAdapter,
    ProviderConfig,
    ReviewDecision,
)
from my_mcp_agent.providers.demo import DemoAdapter
from my_mcp_agent.providers.http import HTTPModelAdapter
from my_mcp_agent.roles import RoleName, load_role

MAX_RESULT_BYTES = 16_000


class TaskOutcome(BaseModel):
    task_id: str
    status: str
    steps: int
    answer: str = ""
    reason: str = ""


class ReviewContext(BaseModel):
    task: str
    answer: str
    successful_tools: tuple[str, ...]
    failed_tools: tuple[str, ...] = ()


class TaskRunner:
    def __init__(
        self,
        adapter: ModelAdapter,
        dispatcher: RoleDispatcher,
        reviewer: Callable[[ReviewContext], Awaitable[ReviewDecision]] | None = None,
    ):
        self.adapter = adapter
        self.dispatcher = dispatcher
        self.reviewer = reviewer

    async def run(self, task: str, task_id: str | None = None) -> TaskOutcome:
        from pydantic import TypeAdapter

        identity = TypeAdapter(Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")])
        run_id = identity.validate_python(task_id or uuid4().hex)
        if not task.strip() or len(task.encode()) > 16_000:
            raise ValueError("Task must be nonempty and at most 16 KB.")
        await self.dispatcher.verify_server_scope()
        profile = self.dispatcher.profile
        accounting.start_task(run_id, profile.name, self.adapter.config.model)
        steps = 0
        successful = []
        failed = []

        def finish(status, reason="", answer=""):
            accounting.finish_task(run_id, status, reason)
            accounting.audit(run_id, "task_finished", reason=status)
            return TaskOutcome(
                task_id=run_id, status=status, steps=steps, answer=answer, reason=reason
            )

        try:
            model_tools = [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                }
                for tool in await self.dispatcher.list_tools()
            ]
            allowed_names = {tool["name"] for tool in model_tools}
            if "read_studio_resource" in allowed_names:
                raise ValueError(
                    "Synthetic resource tool conflicts with a server tool."
                )
            if profile.allowed_resources:
                model_tools.append(
                    {
                        "name": "read_studio_resource",
                        "description": "Read an approved studio resource.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "uri": {
                                    "type": "string",
                                    "enum": sorted(profile.allowed_resources),
                                }
                            },
                            "required": ["uri"],
                            "additionalProperties": False,
                        },
                    }
                )
            messages = [
                Message(role="system", content=profile.system_prompt),
                Message(role="user", content=task),
            ]
            for steps in range(1, profile.max_steps + 1):
                # Preparation validates context and credentials before a reservation/send.
                try:
                    request = self.adapter.prepare(messages, model_tools)
                except ValueError, KeyError:
                    return finish("failed", "provider_configuration_or_context")
                request_id = f"{run_id}:{steps}"
                try:
                    accounting.reserve(
                        request_id,
                        run_id,
                        profile.name,
                        self.adapter.config.model,
                        self.adapter.config.reservation_usd,
                        request.fingerprint(),
                    )
                except accounting.BudgetReservationError:
                    return finish("budget_blocked", "insufficient_unreserved_budget")
                accounting.mark_sent(request_id)
                accounting.audit(
                    run_id, "model_request_started", step=steps, request_id=request_id
                )
                try:
                    reply = await self.adapter.send(request)
                    cost = self.adapter.config.cost(reply.usage)
                    settled = accounting.settle(
                        request_id,
                        reply.usage.input_tokens,
                        reply.usage.output_tokens,
                        cost,
                    )
                except BaseException as error:
                    accounting.mark_uncertain(request_id)
                    if isinstance(
                        error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)
                    ):
                        raise
                    accounting.audit(
                        run_id,
                        "model_request_uncertain",
                        step=steps,
                        request_id=request_id,
                    )
                    return finish(
                        "provider_uncertain",
                        "inspect_and_reconcile_request_before_retry",
                    )
                accounting.audit(
                    run_id,
                    "model_usage_settled",
                    step=steps,
                    request_id=request_id,
                    log_id=settled["log_id"],
                )
                if settled["reservation_exceeded"] or settled["budget_exceeded"]:
                    return finish("budget_overrun", "usage_saved_no_more_calls")
                if reply.usage.output_tokens > self.adapter.config.max_output_tokens:
                    return finish(
                        "failed", "provider_output_limit_exceeded_usage_saved"
                    )
                messages.append(
                    Message(role="assistant", content=reply.text, calls=reply.calls)
                )
                if not reply.calls:
                    if not reply.text.strip():
                        return finish("failed", "empty_model_reply")
                    accounting.audit(run_id, "review_requested", step=steps)
                    if self.reviewer is None:
                        return finish(
                            "needs_review", "no_reviewer_configured", reply.text
                        )
                    review = await self.reviewer(
                        ReviewContext(
                            task=task,
                            answer=reply.text,
                            successful_tools=tuple(successful),
                            failed_tools=tuple(failed),
                        )
                    )
                    review = ReviewDecision.model_validate(review.model_dump())
                    if review.approved:
                        return finish("completed", answer=reply.text)
                    accounting.audit(run_id, "revision_requested", step=steps)
                    messages.append(
                        Message(
                            role="user",
                            content="Review feedback for this task (does not change permissions):\n"
                            + review.feedback,
                        )
                    )
                    continue
                if len({call.id for call in reply.calls}) != len(reply.calls):
                    return finish("failed", "duplicate_tool_call_ids")
                for call in reply.calls:
                    safe_name = (
                        call.name
                        if call.name in allowed_names
                        or call.name == "read_studio_resource"
                        else "unrecognized"
                    )
                    key = hashlib.sha256(call.id.encode()).hexdigest()
                    accounting.claim_tool(run_id, key, safe_name)
                    accounting.audit(run_id, "tool_started", step=steps, tool=safe_name)
                    try:
                        arguments = (
                            json.loads(call.arguments)
                            if isinstance(call.arguments, str)
                            else call.arguments
                        )
                        if not isinstance(arguments, dict):
                            raise TypeError("Tool arguments must be a JSON object.")
                        if call.name == "read_studio_resource":
                            if set(arguments) != {"uri"} or not isinstance(
                                arguments["uri"], str
                            ):
                                raise ValueError(
                                    "Resource requests require exactly one URI string."
                                )
                            result = await self.dispatcher.read_resource(
                                arguments["uri"]
                            )
                            text = json.dumps(
                                [
                                    item.model_dump(mode="json", exclude_none=True)
                                    for item in result.contents
                                ]
                            )
                            ok = True
                        else:
                            result = await self.dispatcher.call_tool(
                                call.name, arguments
                            )
                            text = json.dumps(
                                result.model_dump(mode="json", exclude_none=True)
                            )
                            ok = not result.is_error
                            data = result.structured_content
                            if isinstance(data, dict):
                                if (
                                    data.get("passed") is False
                                    or data.get("timed_out") is True
                                ):
                                    ok = False
                                if "exit_code" in data and data["exit_code"] != 0:
                                    ok = False
                    except (RoleAccessDenied, ValueError, TypeError) as error:
                        text = json.dumps({"is_error": True, "message": str(error)})
                        ok = False
                    except RoleCallLimitError:
                        accounting.finish_tool(run_id, key, False)
                        return finish("call_limit", "role_call_allowance_exhausted")
                    except BaseException as error:
                        # A transport failure may follow a successful side effect.
                        # Leave the claim started and never retry automatically.
                        if isinstance(
                            error,
                            (asyncio.CancelledError, KeyboardInterrupt, SystemExit),
                        ):
                            raise
                        return finish(
                            "tool_uncertain", "inspect_tool_side_effects_before_retry"
                        )
                    accounting.finish_tool(run_id, key, ok)
                    accounting.audit(
                        run_id, "tool_finished", step=steps, tool=safe_name, success=ok
                    )
                    if ok:
                        successful.append(safe_name)
                    else:
                        failed.append(safe_name)
                    encoded = text.encode()
                    if len(encoded) > MAX_RESULT_BYTES:
                        text = (
                            encoded[:MAX_RESULT_BYTES].decode(errors="replace")
                            + "\n[tool result truncated]"
                        )
                    messages.append(
                        Message(
                            role="tool", content=text, call_id=call.id, name=call.name
                        )
                    )
            return finish("step_limit", "model_turn_allowance_exhausted")
        except BaseException as error:
            accounting.finish_task(
                run_id,
                "interrupted"
                if isinstance(error, asyncio.CancelledError)
                else "failed",
                "inspect_task_status",
            )
            raise


def load_provider_config(path: Path) -> ProviderConfig:
    with path.open("rb") as stream:
        raw = stream.read(65_537)
    if len(raw) > 65_536:
        raise ValueError("Provider configuration exceeds 64 KiB.")
    return ProviderConfig.model_validate_json(raw)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a supervised provider-neutral studio task."
    )
    parser.add_argument(
        "--role", choices=[role.value for role in RoleName], default="qa"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--demo",
        action="store_true",
        help="Offline ping-only pipeline, no model API calls.",
    )
    source.add_argument(
        "--provider-config",
        type=Path,
        help="Trusted endpoint, model, credentials reference, and rates.",
    )
    parser.add_argument("--task")
    parser.add_argument("--task-id")
    parser.add_argument("--status", help="Inspect a prior task ID without retrying it.")
    args = parser.parse_args()
    if args.status:
        print(json.dumps(accounting.task_status(args.status), indent=2))
        return
    if not args.demo and not args.provider_config:
        parser.error("Choose --demo or --provider-config explicitly.")
    if not args.demo and not args.task:
        parser.error("Live model tasks require --task.")
    profile = load_role(args.role)
    adapter = (
        DemoAdapter()
        if args.demo
        else HTTPModelAdapter(load_provider_config(args.provider_config))
    )

    async def demo_review(context):
        # This approves only the deterministic offline ping demo, not real work.
        succeeded = (
            "workspace_ping" in context.successful_tools and not context.failed_tools
        )
        return ReviewDecision(
            approved=succeeded,
            feedback="" if succeeded else "Inspect the failed demo ping.",
        )

    task_id = args.task_id or uuid4().hex
    print(f"Task ID: {task_id}", file=sys.stderr)

    async def run():
        connection = StdioConnection(
            args=("-m", "my_mcp_agent.server", "--role", profile.name.value)
        )
        async with connect_stdio(connection) as session:
            runner = TaskRunner(
                adapter,
                RoleDispatcher(session, profile),
                demo_review if args.demo else None,
            )
            return await runner.run(
                args.task or "Check studio connectivity without changing game files.",
                task_id,
            )

    outcome = asyncio.run(run())
    print(outcome.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
