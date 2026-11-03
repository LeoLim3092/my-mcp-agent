# MCP tool input, output, and error contracts

All 13 Phase 1–3 tools publish an input schema and an output schema. Shared
constraints and result types live in `src/my_mcp_agent/contracts.py`.

## Inputs

Python `Annotated` types with Pydantic `Field` constraints generate tool schemas.
Inputs are validated by the MCP SDK before calling the function. Runtime security
and business validation still applies afterward; a schema is not authorization.

| Input | Published constraint |
| --- | --- |
| Workspace path | Strict string, 1–4,096 characters, no NUL; optional listing path defaults to `.` |
| File content/replacement | Strict string, up to the configured character bound; runtime encoded content must also fit `MAX_FILE_WRITE_BYTES` (default 1,000,000 bytes) |
| Patch target | Nonempty string, up to the configured read bound; must match exactly once |
| Agent role/model | Strict string, 1–200 characters, not all whitespace |
| Token count | Strict integer, 0 through 9,223,372,036,854,775,807; booleans, floats, and numeric strings are rejected |
| USD cost | Strict decimal string, at most 12 fractional digits and 23 characters; runtime maximum is 1 billion USD; no exponent notation |
| Branch | Nonempty string, at most 255 characters, no NUL; runtime Git rules and main/master protection still apply |
| Commit message | Nonblank string, at most 4,096 characters |
| Documentation URL | Strict HTTP(S) string, at most 8,192 characters; public-address/port/redirect policy enforced at runtime |
| Blender script | Nonblank string, at most 1,000,000 characters; encoded script also capped at 1,000,000 bytes |
| Optional Blender input | Workspace path or null; defaults to null; runtime requires an existing `.blend` file |

Character bounds and UTF-8 byte bounds differ. For example, 333,334 Chinese
characters fit the content character schema but exceed the default byte limit.
Such a write is rejected before creating parent directories or modifying a file.
Patching also passes the final content through the write limit.

Examples of valid usage inputs:

```json
{
  "agent_role": "programmer",
  "model": "example-model",
  "input_tokens": 100,
  "output_tokens": 25,
  "cost_usd": "0.0125"
}
```

## Outputs

Typed dictionaries publish explicit named fields while preserving ordinary Python
dictionary results for direct callers. The SDK validates successful structured
outputs against their advertised schemas.

| Tool(s) | Structured result |
| --- | --- |
| `workspace_ping`, `read_file`, `write_file`, `patch_file`, `git_status`, `git_diff`, `git_checkpoint`, `fetch_web_docs` | `{ "result": "text" }` |
| `list_directory` | `{ "result": ["file.txt", "assets/"] }` |
| `run_linter`, `run_tests` | `exit_code`, `timed_out`, `stdout`, `stderr`, `output_truncated`, `passed` |
| `run_blender_script` | `exit_code`, `timed_out`, `stdout`, `stderr`, `output_truncated`, `exports` |
| `log_task_usage` | `date`, `timezone`, `spent_usd`, `daily_budget_usd`, `remaining_usd`, `budget_exceeded`, `budget_exhausted`, `task_count`, `input_tokens`, `output_tokens`, `log_id` |

In the installed Python SDK, read `response.structured_content` for successful
data and `response.is_error` for tool failure. Text content is also retained for
compatibility; prefer the structured result instead of parsing that text.

QA failure is a valid completed execution result: a failing lint/test run returns
`passed: false` and its exit code. Similarly, a failed Blender script returns a
nonzero exit code and empty exports. These do not necessarily set the MCP tool
error flag; clients must inspect execution fields as well.

Budget monetary outputs are fixed-point decimal strings, including small amounts
such as `"0.000000000001"`. Callers supply actual cost; the server does not infer
provider pricing or verify that a model call happened.

Resources keep their existing MIME types: hardware/budget JSON, architecture
Markdown, and health-check plain text. Resource reads do not use tool output schemas.

## Expected errors and side effects

Register tool functions through `agent_tool()` in `tool_errors.py`. It preserves
the original signature, type annotations, name, and docstring. Direct Python calls
retain their existing domain exceptions; registered MCP calls translate expected
validation, filesystem, network, and explicit setup/operation failures to `ToolError`.

The real MCP server returns an error result with the actionable message. Unexpected
programming exceptions and malformed successful outputs follow the SDK's generic
error path; their detailed traces remain server-side.

**An over-budget usage log is saved before the error is raised.** The message
includes the log ID, spend, limit, and `Do not retry this log call`. Retrying creates
another entry because logging idempotency is not implemented. A generic transport
failure can still leave the outcome uncertain; reliable retries need idempotency keys.

Schema errors occur before tool execution. Operational errors can occur after
side effects: a Git checkpoint may create a branch before a commit fails, and
multi-file Blender publication is not a transaction. Do not infer rollback from
an MCP error flag.

## Adding a new tool

```python
from typing_extensions import TypedDict

from my_mcp_agent.contracts import WorkspacePath
from my_mcp_agent.tool_errors import agent_tool


class AssetResult(TypedDict):
    path: str
    object_count: int


def inspect_asset(rel_path: WorkspacePath) -> AssetResult:
    """Inspect a permitted asset using the existing security/execution helpers."""
    # Implement actual safe inspection here; never substitute unchecked file I/O.
    raise NotImplementedError


def register_asset_tools(mcp):
    mcp.tool()(agent_tool(inspect_asset))
```

Avoid bare `dict` return annotations for structured results. Use `TypedDict` or a
Pydantic model and add tests for schema generation, successful structured data,
invalid input, expected errors, and malformed outputs. Functions in this project
are synchronous; the current registration error wrapper is for synchronous functions.

## Validation

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_tool_contracts.py' -v
.venv/bin/python -m unittest discover -s tests -v
```

Ten contract tests exercise schema validity for all tools, MCP initialization and
client calls over in-memory transport, structured results, strict input rejection,
saved over-budget warnings, generic crash handling, malformed-output rejection,
and multibyte write limits. The full suite has 58 tests. In-memory client/server
sessions are now covered; production stdio and Inspector checks remain pending.
