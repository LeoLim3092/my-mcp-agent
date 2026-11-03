"""Lint and test filtered workspace snapshots with no network or host credentials."""

import tempfile
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from my_mcp_agent import config
from my_mcp_agent.execution import run_isolated, snapshot_workspace
from my_mcp_agent.security import validate_path


def _run(target: str, kind: str) -> dict:
    path = validate_path(target)
    if not path.exists():
        raise FileNotFoundError("QA target does not exist.")
    relative = path.relative_to(config.ALLOWED_WORKSPACE).as_posix()
    with tempfile.TemporaryDirectory(prefix="studio-qa-") as directory:
        base = Path(directory)
        workspace, output = base / "workspace", base / "output"
        workspace.mkdir()
        output.mkdir()
        snapshot_workspace(workspace)
        if kind == "lint":
            command = [
                "/runtime/bin/ruff",
                "check",
                "--isolated",
                "--no-cache",
                "--",
                relative,
            ]
        else:
            command = [
                "/runtime/bin/python",
                "-I",
                "-m",
                "pytest",
                "-c",
                "/dev/null",
                "--rootdir=/workspace",
                "-p",
                "no:cacheprovider",
                "--",
                relative,
            ]
        result = run_isolated(command, workspace, output)
        result["passed"] = result["exit_code"] == 0 and not result["timed_out"]
        return result


def run_linter(rel_path: str) -> dict:
    """Run Ruff on a file/directory snapshot with a 30-second execution timeout."""
    return _run(rel_path, "lint")


def run_tests(test_target: str) -> dict:
    """Run pytest on a file/directory snapshot; external plugins are disabled.

    Use a workspace-relative path, not pytest flags or node-id expressions.
    Workspace writes do not persist; write temporary test files under /tmp.
    """
    return _run(test_target, "tests")


def register_qa_tools(mcp: MCPServer) -> None:
    for tool in (run_linter, run_tests):
        mcp.tool()(tool)
