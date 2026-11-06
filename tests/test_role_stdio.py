"""Role authorization cannot be bypassed using raw stdio MCP calls."""

import sys
import tempfile
import unittest
from pathlib import Path

from mcp.shared.exceptions import MCPError

from my_mcp_agent.client import StdioConnection, connect_stdio
from my_mcp_agent.config import PROJECT_ROOT
from my_mcp_agent.roles import RoleName, load_role

BOOTSTRAP = """import sys
from pathlib import Path
from my_mcp_agent import config
config.ALLOWED_WORKSPACE = Path(sys.argv[1])
config.LEDGER_DB_PATH = Path(sys.argv[2])
from my_mcp_agent.server import main, create_server
from my_mcp_agent.roles import load_role, RoleProfile
if sys.argv[4] == 'limited':
    profile = load_role(sys.argv[3])
    profile = RoleProfile.model_validate({**profile.model_dump(), 'max_tool_calls': 1, 'max_resource_reads': 1})
    create_server(profile).run()
else:
    main(['--role', sys.argv[3]])
"""


def connection(root, role, limited=False):
    return StdioConnection(
        command=sys.executable,
        cwd=PROJECT_ROOT,
        args=(
            "-c",
            BOOTSTRAP,
            str(root / "game"),
            str(root / "ledger.db"),
            role,
            "limited" if limited else "normal",
        ),
    )


class RoleStdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_roles_expose_exact_capabilities_and_block_control_plane(self):
        for role in RoleName:
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                game = root / "game"
                game.mkdir()
                (game / "GDD.md").write_text("approved design")
                async with connect_stdio(connection(root, role.value)) as session:
                    tools = {tool.name for tool in (await session.list_tools()).tools}
                    resources = {
                        str(resource.uri)
                        for resource in (await session.list_resources()).resources
                    }
                    profile = load_role(role)
                    self.assertEqual(tools, profile.allowed_tools)
                    self.assertEqual(resources, profile.allowed_resources)
                    result = await session.call_tool(
                        "read_file", {"rel_path": "GDD.md"}
                    )
                    self.assertFalse(result.is_error)
                    self.assertIn(
                        "approved design", result.structured_content["result"]
                    )
                    denied = await session.call_tool(
                        "log_task_usage",
                        {
                            "agent_role": "programmer",
                            "model": "fake",
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "cost_usd": "1",
                        },
                    )
                    self.assertTrue(denied.is_error)
                    with self.assertRaises(MCPError):
                        await session.read_resource("studio://telemetry/budget")
                    if role == RoleName.QA:
                        denied = await session.call_tool(
                            "write_file", {"rel_path": "GDD.md", "content": "bad"}
                        )
                        self.assertTrue(denied.is_error)
                self.assertEqual((game / "GDD.md").read_text(), "approved design")
                self.assertFalse((root / "ledger.db").exists())

    async def test_server_call_limits_hold_without_client_dispatcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            async with connect_stdio(connection(root, "qa", limited=True)) as session:
                result = await session.call_tool("workspace_ping", {})
                self.assertFalse(result.is_error)
                result = await session.call_tool("workspace_ping", {})
                self.assertTrue(result.is_error)
                self.assertIn("call limit", result.content[0].text)
                await session.read_resource("studio://telemetry/status")
                with self.assertRaises(MCPError) as error:
                    await session.read_resource("studio://telemetry/status")
                self.assertIn("call limit", str(error.exception))


if __name__ == "__main__":
    unittest.main()
