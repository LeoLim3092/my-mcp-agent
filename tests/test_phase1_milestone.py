"""Phase 1.4 workflow through MCP tool dispatch in a disposable repository.

Run: .venv/bin/python -m unittest discover -s tests -p 'test_phase1_milestone.py' -v
This exercises registration/dispatch, not Inspector or a transport connection.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp.server.mcpserver import MCPServer

from my_mcp_agent import security
from my_mcp_agent.tools import filesystem, git_ops


class Phase1MilestoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_gdd_sandbox_and_feature_checkpoint(self):
        with tempfile.TemporaryDirectory(prefix="phase1-milestone-") as directory:
            workspace = Path(directory).resolve()
            with (
                patch.object(security, "ALLOWED_WORKSPACE", workspace),
                patch.object(filesystem, "ALLOWED_WORKSPACE", workspace),
                patch.object(git_ops, "ALLOWED_WORKSPACE", workspace),
            ):
                # Use the hardened Git runner for setup too: no hooks, signing,
                # global config, or inherited GIT_* repository overrides.
                git_ops._git("init", "-b", "main")
                git_ops._git("config", "user.name", "Milestone Test")
                git_ops._git("config", "user.email", "milestone@example.invalid")
                git_ops._git("commit", "--allow-empty", "-m", "Baseline")
                baseline = git_ops._git("rev-parse", "main").stdout.strip()

                server = MCPServer("Phase1Milestone")
                filesystem.register_filesystem_tools(server)
                git_ops.register_git_tools(server)
                names = {tool.name for tool in await server.list_tools()}
                self.assertTrue({"write_file", "read_file", "patch_file",
                                 "list_directory", "git_status", "git_diff",
                                 "git_checkpoint"} <= names)

                async def call(name, **arguments):
                    result = await server.call_tool(name, arguments)
                    self.assertFalse(result.is_error, str(result))
                    return "\n".join(block.text for block in result.content
                                     if hasattr(block, "text"))

                original = "# Game Design Document\n\nGoal: Explore the island.\n"
                await call("write_file", rel_path="GDD.md", content=original)
                self.assertEqual((workspace / "GDD.md").read_text(), original)
                self.assertIn("1: # Game Design Document",
                                  await call("read_file", rel_path="GDD.md"))
                self.assertIn("GDD.md", await call("list_directory", rel_path="."))

                # Assert the validator's exact exception, plus denial through
                # MCP dispatch. The latter may wrap the original exception.
                with self.assertRaises(security.SandboxViolationError):
                    security.validate_path("/etc/passwd")
                try:
                    denied = await server.call_tool("read_file", {"rel_path": "/etc/passwd"})
                except Exception as error:
                    cause = error
                    while cause is not None and not isinstance(cause, security.SandboxViolationError):
                        cause = cause.__cause__
                    self.assertIsInstance(cause, security.SandboxViolationError)
                else:
                    self.assertTrue(denied.is_error, "Outside read unexpectedly succeeded")

                # A valid call must still succeed following a rejected call.
                await call("patch_file", rel_path="GDD.md",
                           target_snippet="Explore the island.",
                           replacement="Explore the island and find treasure.")
                expected = original.replace("Explore the island.",
                                            "Explore the island and find treasure.")
                self.assertIn("GDD.md", await call("git_status"))
                # Staging is intentionally an explicit setup action, not an MCP tool.
                git_ops._git("add", "--", "GDD.md")
                await call("git_checkpoint", branch_name="test/phase1-milestone",
                           message="Add milestone GDD")
                self.assertEqual(git_ops._git("branch", "--show-current").stdout.strip(),
                                 "test/phase1-milestone")
                self.assertEqual(git_ops._git("show", "HEAD:GDD.md").stdout, expected)
                self.assertEqual(git_ops._git("diff-tree", "--no-commit-id", "--name-only",
                                             "-r", "HEAD").stdout.strip(), "GDD.md")
                self.assertEqual(git_ops._git("rev-parse", "main").stdout.strip(), baseline)
                self.assertEqual(git_ops._git("status", "--porcelain").stdout, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
