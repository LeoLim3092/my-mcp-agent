"""Workspace text-file tools with shared read/write policy enforcement."""

from pathlib import Path

from mcp.server.mcpserver import MCPServer

from my_mcp_agent.config import ALLOWED_WORKSPACE, MAX_FILE_READ_BYTES
from my_mcp_agent.security import SandboxViolationError, validate_path


def _read_text(path: Path) -> str:
    """Bound the actual read, including when a file grows after validation."""
    if not path.is_file():
        raise ValueError("Expected an existing regular file.")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_READ_BYTES + 1)
    if len(data) > MAX_FILE_READ_BYTES:
        raise ValueError(f"File exceeds the {MAX_FILE_READ_BYTES}-byte read limit.")
    if b"\x00" in data:
        raise ValueError("Binary files are not supported; expected UTF-8 text.")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Expected a UTF-8 text file.") from error


def list_directory(rel_path: str = ".") -> list[str]:
    """List immediate readable children, with '/' appended to directories.

    Protected entries and symlinks are omitted. Call again on a subdirectory
    to explore it; this tool does not recursively traverse the workspace.
    """
    directory = validate_path(rel_path)
    if not directory.is_dir():
        raise NotADirectoryError("Expected an existing workspace directory.")
    entries = []
    for child in sorted(directory.iterdir(), key=lambda entry: entry.name):
        try:
            visible = validate_path(str(child))
        except SandboxViolationError:
            continue
        if visible.is_dir():
            entries.append(child.name + "/")
        elif visible.is_file():
            entries.append(child.name)
    return entries


def read_file(rel_path: str) -> str:
    """Read a UTF-8 text file with 1-based line numbers and a byte-size limit."""
    content = _read_text(validate_path(rel_path))
    return "\n".join(
        f"{number}: {line}" for number, line in enumerate(content.splitlines(), start=1)
    )


def write_file(rel_path: str, content: str) -> str:
    """Create or overwrite a UTF-8 file, creating missing parent directories."""
    path = validate_path(rel_path, operation="write")
    if path.exists() and not path.is_file():
        raise ValueError("Expected a regular file destination.")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Recheck after parent creation before opening the destination.
    path = validate_path(rel_path, operation="write")
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(content)
    return f"Wrote {len(content.encode('utf-8'))} bytes."


def patch_file(rel_path: str, target_snippet: str, replacement: str) -> str:
    """Replace exactly one literal snippet in a size-limited UTF-8 file.

    Reject empty, missing, or repeated targets so the caller must identify an
    unambiguous block. Preserve the remaining text and its newline characters.
    """
    if not target_snippet:
        raise ValueError("target_snippet must not be empty.")
    path = validate_path(rel_path, operation="write")
    content = _read_text(path)
    first = content.find(target_snippet)
    if first < 0:
        raise ValueError("Target snippet was not found; file was not changed.")
    if content.find(target_snippet, first + 1) >= 0:
        raise ValueError("Target snippet occurs more than once; file was not changed.")
    updated = content[:first] + replacement + content[first + len(target_snippet):]
    write_file(rel_path, updated)
    return "Replaced one matching snippet."


def register_filesystem_tools(mcp: MCPServer) -> None:
    @mcp.tool()
    def workspace_ping() -> str:
        """Verify filesystem module is loaded and return the sandbox path."""
        return f"Filesystem module active. Workspace: {ALLOWED_WORKSPACE}"

    for tool in (list_directory, read_file, write_file, patch_file):
        mcp.tool()(tool)
