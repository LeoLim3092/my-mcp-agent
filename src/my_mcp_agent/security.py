"""Enforce workspace file-access policies; this is not an OS execution sandbox."""

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

from my_mcp_agent.config import (
    ALLOWED_WORKSPACE,
    BLOCKED_READ_PATTERNS,
    BLOCKED_WRITE_PATTERNS,
    PROTECTED_DIRS,
    WRITE_PROTECTED_NAMES,
)


class SandboxViolationError(PermissionError):
    """A requested file operation violates workspace policy."""


def validate_path(
    rel_path: str,
    *,
    operation: Literal["read", "write"] = "read",
) -> Path:
    """Validate one path for a read/list or write/patch/delete operation.

    File tools must pass operation="write" for every mutation. Directory listing
    tools must validate every child before displaying or descending into it.
    Symlinks are rejected, including internal aliases, to avoid policy bypasses.
    No agent-controlled bypass parameter is provided; Git uses dedicated tools.

    This check cannot prevent concurrent path replacement or constrain tests and
    Blender scripts. Those require OS isolation and safe file-opening practices.
    Filename patterns are defense in depth, not complete secret detection.
    """
    if operation not in {"read", "write"}:
        raise ValueError("operation must be 'read' or 'write'")

    requested = Path(rel_path.strip() or ".")
    candidate = requested if requested.is_absolute() else ALLOWED_WORKSPACE / requested
    # Reject traversal rather than normalize away protected path components.
    if ".." in candidate.parts:
        raise SandboxViolationError("Parent-directory traversal is forbidden.")
    if not candidate.is_relative_to(ALLOWED_WORKSPACE):
        raise SandboxViolationError("Path is outside the allowed game workspace.")

    relative_parts = candidate.relative_to(ALLOWED_WORKSPACE).parts
    current = ALLOWED_WORKSPACE
    patterns = (
        BLOCKED_WRITE_PATTERNS if operation == "write" else BLOCKED_READ_PATTERNS
    )
    for part in relative_parts:
        current = current / part
        name = part.casefold()
        if current.is_symlink():
            raise SandboxViolationError("Symlink access is forbidden.")
        if name in PROTECTED_DIRS or any(
            fnmatchcase(name, pattern) for pattern in patterns
        ):
            raise SandboxViolationError(f"Access to protected entry '{part}' is forbidden.")
        if operation == "write" and name in WRITE_PROTECTED_NAMES:
            raise SandboxViolationError(f"Writing protected entry '{part}' is forbidden.")

    resolved = candidate.resolve()
    if not resolved.is_relative_to(ALLOWED_WORKSPACE):
        raise SandboxViolationError("Resolved path is outside the game workspace.")
    if operation == "write" and resolved == ALLOWED_WORKSPACE:
        raise SandboxViolationError("Replacing or deleting the workspace root is forbidden.")
    return resolved
