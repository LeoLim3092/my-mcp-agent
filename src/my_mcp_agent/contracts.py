"""Published tool input constraints and structured result contracts."""

from typing import Annotated, Literal

from pydantic import Field
from typing_extensions import TypedDict

from my_mcp_agent.config import MAX_FILE_READ_BYTES, MAX_FILE_WRITE_BYTES

WorkspacePath = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=4096,
        pattern=r"^[^\x00]+$",
        description="Path inside the game workspace; relative paths preferred.",
    ),
]
TextContent = Annotated[
    str,
    Field(
        strict=True,
        max_length=MAX_FILE_WRITE_BYTES,
        description="UTF-8 content; the encoded file must also fit the configured byte write limit.",
    ),
]
Snippet = Annotated[
    str, Field(strict=True, min_length=1, max_length=MAX_FILE_READ_BYTES)
]
Identity = Annotated[
    str, Field(strict=True, min_length=1, max_length=200, pattern=r"\S")
]
TokenCount = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
CostUSD = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=23,
        pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?$",
        description="Nonnegative USD decimal string, at most 12 fractional digits and 1 billion USD; no exponent notation.",
    ),
]
BranchName = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=255,
        pattern=r"^[^\x00]+$",
        description="Current or new feature branch; main/master are forbidden.",
    ),
]
CommitMessage = Annotated[
    str, Field(strict=True, min_length=1, max_length=4096, pattern=r"\S")
]
WebURL = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=8192,
        pattern=r"^https?://",
        description="Public HTTP(S) URL, ports 80/443, no embedded credentials.",
    ),
]
BlenderScript = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=1_000_000,
        pattern=r"\S",
        description="Blender Python script, at most 1 MB encoded as UTF-8. Write exports under /output.",
    ),
]


class ExecutionResult(TypedDict):
    exit_code: int
    timed_out: bool
    stdout: str
    stderr: str
    output_truncated: bool


class QAResult(ExecutionResult):
    passed: bool


class BlenderResult(ExecutionResult):
    exports: list[str]


class BudgetSummary(TypedDict):
    date: str
    timezone: Literal["UTC"]
    spent_usd: str
    daily_budget_usd: str
    remaining_usd: str
    budget_exceeded: bool
    budget_exhausted: bool
    task_count: int
    input_tokens: int
    output_tokens: int


class UsageLogResult(BudgetSummary):
    log_id: int
