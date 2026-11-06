"""Provider-neutral configuration and real stdio process integration."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from my_mcp_agent.client import StdioConnection, inspect_server, load_connection
from my_mcp_agent.config import EXECUTION_TIMEOUT_SECONDS, PROJECT_ROOT

# Patch trusted config inside the new process before importing the actual server.
# This runs its real startup/registration/stdio path against temporary state.
BOOTSTRAP = """from pathlib import Path
import sys
from my_mcp_agent import config
config.ALLOWED_WORKSPACE = Path(sys.argv[1])
config.LEDGER_DB_PATH = Path(sys.argv[2])
from my_mcp_agent.server import mcp
mcp.run()
"""


class ConnectionConfigTests(unittest.TestCase):
    def test_provider_is_not_part_of_mcp_connection(self):
        connection = StdioConnection()
        self.assertEqual(connection.args, ("-m", "my_mcp_agent.server"))
        self.assertNotIn("model", StdioConnection.model_fields)
        with self.assertRaises(ValidationError):
            StdioConnection(model="provider-specific-model")
        for timeout in (0, -1, 121):
            with self.subTest(timeout=timeout), self.assertRaises(ValidationError):
                StdioConnection(request_timeout_seconds=timeout)

    def test_default_request_timeout_outlasts_tool_execution_limit(self):
        self.assertGreater(
            StdioConnection().request_timeout_seconds, EXECUTION_TIMEOUT_SECONDS
        )

    def test_trusted_json_configuration_and_size_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connection.json"
            path.write_text(
                json.dumps(
                    {"command": sys.executable, "args": ["-m", "my_mcp_agent.server"]}
                )
            )
            self.assertEqual(load_connection(path).command, sys.executable)
            path.write_bytes(b" " * 65_537)
            with self.assertRaises(ValueError):
                load_connection(path)


class StdioConnectionTests(unittest.IsolatedAsyncioTestCase):
    def connection(self, base):
        return StdioConnection(
            command=sys.executable,
            args=("-c", BOOTSTRAP, str(base / "game"), str(base / "ledger.db")),
            cwd=PROJECT_ROOT,
            request_timeout_seconds=15,
        )

    async def test_real_stdio_lists_tools_reads_resources_and_restarts(self):
        with tempfile.TemporaryDirectory(prefix="studio-stdio-") as directory:
            base = Path(directory)
            connection = self.connection(base)
            resources = (
                "studio://telemetry/hardware",
                "studio://telemetry/budget",
                "studio://memory/architecture",
            )
            report = await inspect_server(connection, resources)
            self.assertTrue(report["initialized"])
            self.assertEqual(report["transport"], "stdio")
            self.assertEqual(len(report["tools"]), 13)
            self.assertEqual(len(set(report["tools"])), 13)
            self.assertEqual(len(report["resources"]), 4)
            self.assertIn(str(base / "game"), report["workspace_ping"]["result"])
            hardware = json.loads(report["resource_results"][resources[0]][0]["text"])
            self.assertGreater(hardware["memory"]["total_bytes"], 0)
            budget = json.loads(report["resource_results"][resources[1]][0]["text"])
            self.assertEqual(budget["task_count"], 0)
            self.assertEqual(budget["timezone"], "UTC")
            self.assertTrue((base / "ledger.db").is_file())
            game = base / "game/GDD.md"
            game.write_text("Preserve this game design")
            restarted = await inspect_server(connection, (resources[2],))
            self.assertEqual(set(restarted["tools"]), set(report["tools"]))
            self.assertIn(
                "Preserve this game design",
                restarted["resource_results"][resources[2]][0]["text"],
            )
            self.assertEqual(game.read_text(), "Preserve this game design")

    async def test_missing_server_command_reports_underlying_error(self):
        with self.assertRaises(FileNotFoundError):
            await inspect_server(StdioConnection(command="/nonexistent/studio-server"))

    async def test_unknown_resource_is_rejected_without_game_writes(self):
        with tempfile.TemporaryDirectory(prefix="studio-stdio-") as directory:
            base = Path(directory)
            with self.assertRaises(ValueError):
                await inspect_server(
                    self.connection(base), ("studio://unlisted/private",)
                )
            self.assertEqual(list((base / "game").iterdir()), [])
            self.assertFalse((base / "ledger.db").exists())


if __name__ == "__main__":
    unittest.main()
