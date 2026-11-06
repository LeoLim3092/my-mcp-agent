# Phase 4: provider-neutral agents and MCP clients

The studio MCP server supplies capabilities, not an LLM. The model belongs to the
host application or future custom orchestrator. Claude Desktop is one optional
host; the server has no Claude model dependency.

```text
User task
   |
MCP-capable host OR custom orchestrator
   |-- trusted role/permission policy
   |-- model adapter --> selected hosted or local model
   |-- MCP client
          |
     Studio MCP server
          |
     Files, Git, QA, Blender, telemetry, approved memory
```

MCP standardizes communication between the host/client and the tool server.
It does not make every raw model API interchangeable. A host/provider adapter must
translate tool schemas, model tool-call responses, tool results, and usage data.
A model must be compatible with that adapter's tool-calling requirements. Models
without supported tool calling must be rejected or handled by an explicitly
designed separate workflow; no universal-model compatibility is claimed.

See the [official MCP architecture](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/architecture/index.mdx).

## Phase 4.1 implemented: model-independent connection

`src/my_mcp_agent/client.py` provides:

- `StdioConnection`: trusted operator command, arguments, working directory, timeout.
- `connect_stdio()`: launches the server, initializes MCP, yields a session, and closes it afterward.
- `inspect_server()`: lists tools/resources, calls `workspace_ping`, and optionally reads advertised resources.
- A diagnostic CLI that needs no LLM, provider account, API key, or paid model call.

From the project root, use the existing environment:

```bash
.venv/bin/python -m my_mcp_agent.client
```

Expected: JSON showing `initialized: true`, 13 tools, four resources, and the workspace ping result.
This starts the real server; startup creates `~/game_workspace` if it is missing.

Read selected resources:

```bash
.venv/bin/python -m my_mcp_agent.client \
  --resource studio://telemetry/hardware \
  --resource studio://telemetry/budget \
  --resource studio://memory/architecture
```

Reading the budget can initialize `studio_ledger.db`. The diagnostic does not write
game files or call a model. Resource content can include private project context;
do not publish diagnostic output without checking it.

To configure another trusted launch command:

```bash
.venv/bin/python -m my_mcp_agent.client --config config/mcp-server.example.json
```

The example uses this repository's WSL path; adjust it for another checkout.
Command configuration is executable authority. Keep it outside the agent-writable
workspace and never let a model supply or edit it. Do not put credentials in command
arguments. LLM provider/model settings are intentionally absent from this file.
The SDK uses its minimal default subprocess environment; arbitrary API credentials
are not added by this connector.

## Connect an existing MCP host

Choose a host supporting local stdio MCP and a model that the host can use with
tools. Configure its server launch settings using the host's required format.
The following common `mcpServers` layout is an example, not a universal settings
schema for every host. No desktop application configuration has been modified.

Native Linux/WSL host:

```json
{
  "mcpServers": {
    "solo-game-studio": {
      "command": "/home/leolim/repo/my-mcp-agent/.venv/bin/python",
      "args": ["-m", "my_mcp_agent.server"]
    }
  }
}
```

Windows host launching the WSL installation:

```json
{
  "mcpServers": {
    "solo-game-studio": {
      "command": "wsl.exe",
      "args": [
        "--exec",
        "/home/leolim/repo/my-mcp-agent/.venv/bin/python",
        "-m",
        "my_mcp_agent.server"
      ]
    }
  }
}
```

Use the correct distribution if the default WSL distribution is not the one
containing this checkout. An absolute Python path avoids dependence on whether a
noninteractive WSL shell adds `uv` to PATH. Install project dependencies first with
`uv sync`. The model selection remains in the host, independent of these MCP settings.

After connecting, verify tools are listed and read `studio://memory/architecture`.
Then try a supervised task with the existing tool protections. Desktop/Inspector
UI checks are still manual, separate from the automated stdio integration test.

## Phase 4.2 implemented: roles and authorization

Trusted YAML profiles now define the writer, programmer, artist, and QA roles.
They remain separate from model/provider assignments. A checked dispatcher and
role-scoped server enforce tool/resource permissions and call allowances. Raw
MCP calls cannot bypass the scoped server's registered capability set.

Use `python -m my_mcp_agent.server --role qa` (or another named role) for an
agent connection. The original unscoped diagnostic server remains operator-only.
See [role setup and enforcement](phase4-roles.md) for profiles, limits, launch
examples, tests, and the remaining Phase 4.3 work.

## Phase 4.3 implemented: model adapters and orchestration

The custom orchestrator separates these concerns:

| Component | Responsibility |
| --- | --- |
| Role policy | Enforce allowed tools/resources in trusted code |
| Model configuration | Select provider/endpoint/model and reference credentials securely |
| Provider adapter | Translate messages, tool schemas/calls/results, usage, and model capabilities |
| MCP connection | Execute authorized calls against the same studio server |
| Budget controller | Gate/reserve spending before model requests; settle actual usage idempotently |
| Task loop | Bound steps, handle errors/reviews, and return completion/results |

Hosted and local models can use the implemented Chat Completions-compatible or
native Ollama adapter. Other protocols need an additional adapter. The task loop
includes role enforcement, budget reservations, idempotent settlement, and review
hooks; see [Phase 4 orchestration](phase4-orchestrator.md). A generic
endpoint compatibility label is not sufficient proof that a model supports the
required schemas, tools, streaming semantics, or usage reporting.

## Validation

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_client.py' -v
.venv/bin/python -m unittest discover -s tests -v
```

Five connection tests cover provider-independent configuration, config size and
validation, actual stdio process initialization, discovery of all 13 tools/four
resources, live JSON resource reads, memory reads, restart preservation, and
rejection of unadvertised diagnostic resources, and missing-command error reporting. Tests bootstrap the real server
with temporary workspace/ledger settings; the user's game workspace and ledger
are not modified. These tests do not invoke a provider or validate a desktop UI.

Validation result: all five connection tests passed. The suite had 63 tests at the Phase 4.1 checkpoint; Phase 4.2 brings it to 74 passing tests. No LLM provider/API account was required.

Phase 4.3 now provides the task-loop CLI, two HTTP protocols, reservations, settlement, and recovery. See its guide; the combined suite is 99 tests, while live provider/desktop validation remains pending.
