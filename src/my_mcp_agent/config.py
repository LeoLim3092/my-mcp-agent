"""Studio paths, limits, and file-access policy constants."""

from pathlib import Path

# Keep agent-writable game files separate from trusted MCP code and accounting.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
ALLOWED_WORKSPACE: Path = (Path.home() / "game_workspace").resolve()
# Git metadata and runtime internals must not be accessed through raw file tools.
PROTECTED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".mcp_cache",
        ".ssh",
        ".aws",
        ".azure",
        ".gnupg",
    }
)
BLOCKED_READ_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    "id_dsa*",
    "credentials",
    "credentials.json",
    "application_default_credentials.json",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    ".mcp.json",
    "claude_desktop_config.json",
    "studio_ledger.db*",
)
# Configuration may be useful context to read, but agents cannot rewrite it.
WRITE_PROTECTED_NAMES: frozenset[str] = frozenset(
    {".agents", ".codex", ".claude", ".config", "roles", "agents.md"}
)
BLOCKED_WRITE_PATTERNS: tuple[str, ...] = BLOCKED_READ_PATTERNS

DAILY_BUDGET_USD: float = 5.00
MAX_FILE_READ_BYTES: int = 1_000_000
MAX_FILE_WRITE_BYTES: int = 1_000_000
LEDGER_DB_PATH: Path = PROJECT_ROOT / "studio_ledger.db"

# Phase 3 execution is Linux/Bubblewrap only and fails closed if unavailable.
EXECUTION_TIMEOUT_SECONDS: int = 30
EXECUTION_OUTPUT_BYTES: int = 100_000
SNAPSHOT_MAX_BYTES: int = 100_000_000
SNAPSHOT_MAX_FILES: int = 5_000
BLENDER_EXECUTABLE: str = (
    str(PROJECT_ROOT / ".runtime/blender/blender")
    if (PROJECT_ROOT / ".runtime/blender/blender").is_file()
    else "blender"
)  # Trusted operator setting.
MEMORY_DOCUMENTS: tuple[str, ...] = ("GDD.md", "ARCHITECTURE.md", "CODING_STANDARDS.md")
WEB_MAX_BYTES: int = 2_000_000
