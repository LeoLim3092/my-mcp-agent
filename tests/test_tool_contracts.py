"""Published schemas and real MCP client/server result/error contracts."""

import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import anyio
from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared.memory import create_client_server_memory_streams

from my_mcp_agent import config, ledger, security
from my_mcp_agent.contracts import QAResult
from my_mcp_agent.tool_errors import agent_tool
from my_mcp_agent.tools import budget, external, filesystem, git_ops, qa_runner


def make_server():
    server = MCPServer("ToolContractTests")
    for register in (
        filesystem.register_filesystem_tools,
        git_ops.register_git_tools,
        budget.register_budget_tools,
        qa_runner.register_qa_tools,
        external.register_external_tools,
    ):
        register(server)
    return server


@asynccontextmanager
async def connected(server):
    async with (
        create_client_server_memory_streams() as (
            client_streams,
            server_streams,
        ),
        anyio.create_task_group() as group,
    ):
        lowlevel = server._lowlevel_server
        group.start_soon(
            lowlevel.run, *server_streams, lowlevel.create_initialization_options()
        )
        try:
            async with ClientSession(
                *client_streams, read_timeout_seconds=15
            ) as client:
                await client.initialize()
                yield client
        finally:
            group.cancel_scope.cancel()


class ToolContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for module, name, value in (
            (security, "ALLOWED_WORKSPACE", self.root),
            (config, "ALLOWED_WORKSPACE", self.root),
            (git_ops, "ALLOWED_WORKSPACE", self.root),
            (filesystem, "ALLOWED_WORKSPACE", self.root),
            (ledger, "LEDGER_DB_PATH", self.root / "private.db"),
            (ledger, "DAILY_BUDGET_USD", 5.0),
        ):
            override = patch.object(module, name, value)
            override.start()
            self.addCleanup(override.stop)

    async def test_all_tools_publish_valid_input_and_output_schemas(self):
        tools = {tool.name: tool for tool in await make_server().list_tools()}
        self.assertEqual(len(tools), 13)
        for tool in tools.values():
            with self.subTest(tool=tool.name):
                Draft202012Validator.check_schema(tool.input_schema)
                self.assertIsNotNone(tool.output_schema)
                Draft202012Validator.check_schema(tool.output_schema)
        expected = {
            "run_linter": {
                "exit_code",
                "passed",
                "timed_out",
                "stdout",
                "stderr",
                "output_truncated",
            },
            "run_tests": {
                "exit_code",
                "passed",
                "timed_out",
                "stdout",
                "stderr",
                "output_truncated",
            },
            "run_blender_script": {
                "exit_code",
                "exports",
                "timed_out",
                "stdout",
                "stderr",
                "output_truncated",
            },
            "log_task_usage": {"log_id", "spent_usd", "remaining_usd", "task_count"},
        }
        for name, required in expected.items():
            self.assertTrue(required <= set(tools[name].output_schema["required"]))
        tokens = tools["log_task_usage"].input_schema["properties"]["input_tokens"]
        self.assertEqual(tokens["minimum"], 0)
        self.assertEqual(tokens["maximum"], 2**63 - 1)
        self.assertEqual(
            tools["run_blender_script"].input_schema["properties"]["script_content"][
                "maxLength"
            ],
            1_000_000,
        )
        self.assertEqual(
            tools["write_file"].input_schema["properties"]["content"]["maxLength"],
            1_000_000,
        )

    async def test_client_receives_structured_usage_result_matching_schema(self):
        server = make_server()
        async with connected(server) as client:
            listed = {tool.name: tool for tool in (await client.list_tools()).tools}
            result = await client.call_tool(
                "log_task_usage",
                {
                    "agent_role": "qa",
                    "model": "fake-model",
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "cost_usd": "0.000000000001",
                },
            )
            self.assertFalse(result.is_error, result)
            self.assertIsNotNone(result.structured_content)
            Draft202012Validator(listed["log_task_usage"].output_schema).validate(
                result.structured_content
            )
            self.assertEqual(result.structured_content["spent_usd"], "0.000000000001")
            self.assertEqual(result.structured_content["log_id"], 1)
            self.assertEqual(
                json.loads(result.content[0].text), result.structured_content
            )

    async def test_client_rejects_invalid_inputs_without_recording_usage(self):
        async with connected(make_server()) as client:
            base = {
                "agent_role": "qa",
                "model": "fake",
                "input_tokens": 1,
                "output_tokens": 1,
                "cost_usd": "0.01",
            }
            for field, value in (
                ("input_tokens", -1),
                ("input_tokens", True),
                ("input_tokens", 1.5),
                ("input_tokens", "1"),
                ("agent_role", " "),
                ("model", "m" * 201),
                ("cost_usd", 0.01),
                ("cost_usd", "NaN"),
                ("cost_usd", "1e-3"),
                ("cost_usd", "-1"),
            ):
                with self.subTest(field=field, value=value):
                    result = await client.call_tool(
                        "log_task_usage", {**base, field: value}
                    )
                    self.assertTrue(result.is_error, result)
            self.assertEqual(ledger.get_budget_summary()["task_count"], 0)
            invalid_patch = await client.call_tool(
                "patch_file",
                {"rel_path": "file.txt", "target_snippet": "", "replacement": "x"},
            )
            self.assertTrue(invalid_patch.is_error)
            invalid_script = await client.call_tool(
                "run_blender_script", {"script_content": " "}
            )
            self.assertTrue(invalid_script.is_error)

    async def test_over_budget_error_keeps_saved_and_no_retry_warning(self):
        with patch.object(ledger, "DAILY_BUDGET_USD", 0.1):
            async with connected(make_server()) as client:
                result = await client.call_tool(
                    "log_task_usage",
                    {
                        "agent_role": "qa",
                        "model": "fake",
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "cost_usd": "0.125",
                    },
                )
                self.assertTrue(result.is_error)
                message = result.content[0].text
                self.assertIn("Usage recorded as log 1", message)
                self.assertIn("Do not retry", message)
                self.assertEqual(ledger.get_budget_summary()["task_count"], 1)
                self.assertEqual(ledger.get_budget_summary()["spent_usd"], "0.125")

    async def test_expected_errors_are_readable_but_crashes_stay_generic(self):
        server = make_server()

        def crash() -> str:
            raise RuntimeError("private crash detail must not reach the client")

        server.tool()(agent_tool(crash))
        async with connected(server) as client:
            blocked = await client.call_tool("read_file", {"rel_path": "/etc/passwd"})
            self.assertTrue(blocked.is_error)
            self.assertIn("outside", blocked.content[0].text)
            with self.assertLogs("mcp.server.mcpserver.server", level="ERROR"):
                crashed = await client.call_tool("crash", {})
            self.assertTrue(crashed.is_error)
            self.assertNotIn("private crash detail", crashed.content[0].text)

    async def test_qa_structured_output_matches_published_schema(self):
        result: QAResult = {
            "exit_code": 1,
            "timed_out": False,
            "stdout": "lint failure",
            "stderr": "",
            "output_truncated": False,
            "passed": False,
        }
        with patch.object(qa_runner, "_run", return_value=result):
            async with connected(make_server()) as client:
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                response = await client.call_tool(
                    "run_linter", {"rel_path": "sample.py"}
                )
                self.assertFalse(response.is_error)
                self.assertEqual(response.structured_content, result)
                Draft202012Validator(tools["run_linter"].output_schema).validate(
                    response.structured_content
                )

    async def test_multibyte_write_limit_preserves_file_and_parent_state(self):
        filesystem.write_file("file.txt", "original")
        async with connected(make_server()) as client:
            too_large = (
                "樹" * 333_334
            )  # Character schema fits, UTF-8 byte limit does not.
            result = await client.call_tool(
                "write_file", {"rel_path": "file.txt", "content": too_large}
            )
            self.assertTrue(result.is_error)
            self.assertIn("write limit", result.content[0].text)
            self.assertEqual((self.root / "file.txt").read_text(), "original")
            result = await client.call_tool(
                "write_file", {"rel_path": "new/file.txt", "content": too_large}
            )
            self.assertTrue(result.is_error)
            self.assertFalse((self.root / "new").exists())

    async def test_file_and_git_success_results_match_schema(self):
        git_ops._git("init", "-b", "main")
        git_ops._git("config", "user.name", "Contract Test")
        git_ops._git("config", "user.email", "contract@example.invalid")
        filesystem.write_file("game.txt", "old\n")
        git_ops._git("add", "--", "game.txt")
        git_ops._git("commit", "-m", "Baseline")
        async with connected(make_server()) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}

            async def checked(name, arguments):
                response = await client.call_tool(name, arguments)
                self.assertFalse(response.is_error, response)
                Draft202012Validator(tools[name].output_schema).validate(
                    response.structured_content
                )
                return response.structured_content["result"]

            self.assertIn(str(self.root), await checked("workspace_ping", {}))
            await checked("write_file", {"rel_path": "notes.txt", "content": "notes"})
            self.assertIn("notes.txt", await checked("list_directory", {}))
            await checked(
                "patch_file",
                {"rel_path": "game.txt", "target_snippet": "old", "replacement": "new"},
            )
            self.assertIn("new", await checked("read_file", {"rel_path": "game.txt"}))
            self.assertIn("game.txt", await checked("git_status", {}))
            self.assertIn("+new", await checked("git_diff", {"file_path": "game.txt"}))
            git_ops._git("add", "--", "game.txt")
            await checked(
                "git_checkpoint",
                {"branch_name": "test/contracts", "message": "Contract checkpoint"},
            )
            self.assertEqual(git_ops._git("show", "HEAD:game.txt").stdout, "new\n")

    async def test_blender_structured_result_matches_schema(self):
        fake = {
            "exit_code": 0,
            "timed_out": False,
            "stdout": "done",
            "stderr": "",
            "output_truncated": False,
        }
        with (
            patch.object(external.shutil, "which", return_value="/usr/bin/python3"),
            patch.object(external, "run_isolated", return_value=fake),
        ):
            async with connected(make_server()) as client:
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                response = await client.call_tool(
                    "run_blender_script", {"script_content": "print('done')"}
                )
                self.assertFalse(response.is_error, response)
                Draft202012Validator(
                    tools["run_blender_script"].output_schema
                ).validate(response.structured_content)
                self.assertEqual(response.structured_content["exports"], [])

    async def test_invalid_output_is_reported_as_tool_error(self):
        with patch.object(qa_runner, "_run", return_value={"passed": True}):
            async with connected(make_server()) as client:
                with self.assertLogs("mcp.server.mcpserver.server", level="ERROR"):
                    response = await client.call_tool(
                        "run_tests", {"test_target": "tests"}
                    )
                self.assertTrue(response.is_error)


if __name__ == "__main__":
    unittest.main()
