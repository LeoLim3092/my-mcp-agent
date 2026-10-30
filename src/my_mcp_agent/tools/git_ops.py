"""Git operations limited to a standalone repository at the workspace root."""

import os
import subprocess
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from my_mcp_agent.config import ALLOWED_WORKSPACE
from my_mcp_agent.security import SandboxViolationError, validate_path

GIT_TIMEOUT_SECONDS = 30
PROTECTED_BRANCHES = frozenset({"main", "master"})


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    # Inherited Git overrides must not redirect operations to another repository.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_LITERAL_PATHSPECS="1")
    try:
        result = subprocess.run(
            ["git", "--no-pager", "-c", f"core.hooksPath={os.devnull}",
             "-c", "core.fsmonitor=false", "-c", "commit.gpgSign=false", *args],
            cwd=ALLOWED_WORKSPACE, env=env, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git operation exceeded its 30-second timeout.") from error
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or "Git operation failed.")
    return result


def _require_repository() -> None:
    metadata = ALLOWED_WORKSPACE / ".git"
    # Linked worktrees/submodules can put metadata outside the workspace.
    if metadata.is_symlink() or not metadata.is_dir():
        raise ValueError("Initialize a standalone Git repository at the workspace root first.")
    top = Path(_git("rev-parse", "--show-toplevel").stdout.strip()).resolve()
    git_dir = Path(_git("rev-parse", "--absolute-git-dir").stdout.strip()).resolve()
    if top != ALLOWED_WORKSPACE or git_dir != metadata:
        raise SandboxViolationError("Git repository must belong to the workspace root.")


def git_status() -> str:
    """Return short status, omitting paths blocked by workspace read policy."""
    _require_repository()
    fields = iter(_git("status", "--short", "-z", "--untracked-files=all").stdout.split("\0"))
    entries = []
    for field in fields:
        if not field:
            continue
        status, name = field[:2], field[3:]
        old_name = next(fields) if "R" in status or "C" in status else None
        try:
            validate_path(name)
            if old_name is not None:
                validate_path(old_name)
        except SandboxViolationError:
            continue
        label = repr(name) if old_name is None else f"{old_name!r} -> {name!r}"
        entries.append(f"{status} {label}")
    return "\n".join(entries) or "No visible changes."


def git_diff(file_path: str) -> str:
    """Return unstaged changes for one readable file; untracked files have no diff."""
    _require_repository()
    path = validate_path(file_path)
    if path == ALLOWED_WORKSPACE or path.is_dir():
        raise ValueError("Provide a single file path, not a directory.")
    name = path.relative_to(ALLOWED_WORKSPACE).as_posix()
    return _git("diff", "--no-ext-diff", "--no-textconv", "--", name).stdout


def git_checkpoint(branch_name: str, message: str) -> str:
    """Commit already staged files on the current or a newly created feature branch.

    Never stages files automatically. Existing branches other than the current
    branch are rejected to avoid moving a staged snapshot between histories.
    Main/master cannot be target branches; Git hooks and commit signing are off.
    """
    _require_repository()
    if not branch_name or branch_name.startswith("-") or branch_name.casefold() in PROTECTED_BRANCHES:
        raise ValueError("Choose a feature branch other than main or master.")
    if not message.strip() or "\0" in message:
        raise ValueError("A nonempty commit message without NUL characters is required.")
    if _git("check-ref-format", f"refs/heads/{branch_name}", check=False).returncode:
        raise ValueError("Invalid feature branch name.")
    if any((ALLOWED_WORKSPACE / ".git" / name).exists() for name in (
        "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"
    )):
        raise ValueError("Finish or abort the active Git operation before checkpointing.")
    staged = _git("diff", "--cached", "--name-only", "--no-renames", "-z").stdout
    names = [name for name in staged.split("\0") if name]
    if not names:
        raise ValueError("No staged changes. Stage reviewed files before checkpointing.")
    for name in names:
        validate_path(name, operation="write")
    current = _git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if current.returncode:
        raise ValueError("Detached HEAD is unsupported; select a branch first.")
    if current.stdout.strip() != branch_name:
        exists = _git("show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}", check=False)
        if exists.returncode == 0:
            raise ValueError("Target branch already exists; select it manually before checkpointing.")
        _git("switch", "-c", branch_name)
    # Defense in depth: verify the actual branch immediately before committing.
    actual = _git("symbolic-ref", "--short", "HEAD").stdout.strip()
    if actual != branch_name or actual.casefold() in PROTECTED_BRANCHES:
        raise SandboxViolationError("Refusing to commit outside the requested feature branch.")
    result = _git("commit", "-m", message)
    return result.stdout.strip()


def register_git_tools(mcp: MCPServer) -> None:
    for tool in (git_status, git_diff, git_checkpoint):
        mcp.tool()(tool)
