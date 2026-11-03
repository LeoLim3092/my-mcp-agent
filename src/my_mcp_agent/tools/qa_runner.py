"""Lint and test filtered workspace snapshots with no network or host credentials."""

import tempfile
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from my_mcp_agent import config
from my_mcp_agent.contracts import QAResult, WorkspacePath
from my_mcp_agent.execution import run_isolated, snapshot_workspace
from my_mcp_agent.security import validate_path
from my_mcp_agent.tool_errors import agent_tool


def _run(target: str, kind: str) -> QAResult:
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
                "-c",
                (
                    "import sys, pytest; sys.path[:0] = ['/workspace', '/workspace/src']; "
                    "raise SystemExit(pytest.main(sys.argv[1:]))"
                ),
                "-c",
                "/dev/null",
                "--rootdir=/workspace",
                "-p",
                "no:cacheprovider",
                "--",
                relative,
            ]
        result = run_isolated(command, workspace, output)
        return {
            **result,
            "passed": result["exit_code"] == 0 and not result["timed_out"],
        }


def run_linter(rel_path: WorkspacePath) -> QAResult:
    """Run Ruff on a file/directory snapshot with a 30-second execution timeout."""
    return _run(rel_path, "lint")


def run_tests(test_target: WorkspacePath) -> QAResult:
    """Run pytest on a file/directory snapshot; external plugins are disabled.

    Use a workspace-relative path, not pytest flags or node-id expressions.
    Workspace root and src/ are explicit import roots inside isolation. Project
    dependencies must already be installed by the operator in the server runtime;
    no workspace installation scripts run automatically. Workspace writes do not
    persist; write temporary test files under /tmp.
    """
    return _run(test_target, "tests")


def register_qa_tools(mcp: MCPServer) -> None:
    for tool in (run_linter, run_tests):
        mcp.tool()(agent_tool(tool))
