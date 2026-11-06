# Phase 4.2: roles and enforced permissions

Role profiles are trusted YAML files in the repository's `roles/` directory,
outside the agent-writable game workspace. They contain no model name, provider,
endpoint, launch command, or credential. Changing a model will not change a role's
permissions. Model assignment is configured separately through the Phase 4.3 adapters and task loop.

## Default roles

All four roles can ping, list workspace files, read permitted text files, and read
architecture memory and the status resource. Additional permissions are:

| Role | Additional tools | Additional resources |
| --- | --- | --- |
| Writer | `write_file`, `fetch_web_docs` | None |
| Programmer | `write_file`, `patch_file`, `git_status`, `git_diff`, `git_checkpoint`, `run_linter`, `run_tests` | Hardware telemetry |
| Artist | `run_blender_script` | Hardware telemetry |
| QA | `git_status`, `git_diff`, `run_linter`, `run_tests` | Hardware telemetry |

No agent role can call `log_task_usage` or read the budget resource. Those remain
in the trusted operator/orchestrator control plane. No model-exposed tool can load
another role, change launch settings, or alter accounting identity.

Role tool permissions are capability permissions, not file-extension rules or
human approval gates. A writer's write tool can write any path permitted by the
shared workspace policy. Programmer checkpoints still need reviewed, manually
staged changes. Existing execution and filesystem protections continue to apply.

## Enforcement at two boundaries

`authorization.py` provides:

1. **RoleDispatcher:** the future model loop receives this facade, never the raw
   MCP session. Discovery is filtered, and every tool/resource call is independently
   checked before forwarding. A guessed name or a `role` field in model-generated
   arguments cannot expand the assigned policy.
2. **RoleRegistrar:** a dedicated role-scoped server registers only permitted
   capabilities. Even a raw MCP client bypassing the dispatcher cannot call an
   unregistered tool or read an unregistered resource. Server-side counters enforce
   tool/resource allowances as well.

Code-level capability ceilings in `roles.py` prevent YAML from granting tools
outside that role's approved maximum. Unknown settings and provider/model fields
are rejected. Role loading accepts one of four names, not arbitrary file paths;
it uses safe YAML, a 64 KiB limit, and refuses linked/nonregular profile files.
Profiles are immutable snapshots. The dispatcher and registrar revalidate them
when constructed, including profiles copied without Pydantic validation.

This enforces model-generated requests inside this system. It does not sandbox
arbitrary Python code running in the trusted orchestrator process or restrict
other tools supplied independently by a desktop host.

## Launch a scoped server

For a QA client, configure the server command as:

```bash
.venv/bin/python -m my_mcp_agent.server --role qa
```

That command is a stdio server, not a terminal chat interface. A compatible host
or `connect_stdio()` connects through its stdin/stdout. Replace `qa` with `writer`,
`programmer`, or `artist` to select a different trusted role at startup.

Inspect the QA connection with the provider-neutral diagnostic client:

```bash
.venv/bin/python -m my_mcp_agent.client \
  --config config/mcp-qa.example.json \
  --resource studio://memory/architecture
```

Expected: seven tools and three resources, including no write, checkpoint, Blender,
usage logging, or budget-resource capability. Its ping/resource reads consume the
same server-process allowance as other authorized operations.

**Unscoped mode remains operator-only.** Existing `mcp run server.py` / Inspector
module exports and `python -m my_mcp_agent.server` without `--role` retain all 13
tools and four resources for diagnostics and trusted accounting. Do not give that
unscoped connection to a model and assume its prompt enforces a role. The global
unscoped server object is constructed for existing module launch compatibility;
`--role` starts a separate scoped instance and never serves that global object.

No user's desktop configuration has been modified. Add the `--role` argument to
the chosen host's launch command when manually connecting a role.

## Use the dispatcher in trusted client code

```python
from my_mcp_agent.authorization import RoleDispatcher
from my_mcp_agent.client import connect_stdio, load_connection
from my_mcp_agent.roles import load_role
from pathlib import Path

# Operator-selected configuration and role, never values chosen by the model.
connection = load_connection(Path("config/mcp-qa.example.json"))
profile = load_role("qa")

async with connect_stdio(connection) as session:
    dispatcher = RoleDispatcher(session, profile)
    tools_for_adapter = await dispatcher.list_tools()
    # The future model adapter receives profile.system_prompt and allowed schemas.
    result = await dispatcher.call_tool("read_file", {"rel_path": "GDD.md"})
    # dispatcher.call_tool("write_file", ...) would raise RoleAccessDenied.
```

The snippet belongs inside an async function. Model-generated tool names/arguments
must pass through the same dispatcher. Do not let the adapter access `session`,
connection configuration, or role-file editing APIs.

## Limits and lifecycle

Profiles declare `max_steps`, `max_tool_calls`, and `max_resource_reads`, each within
1–100. Defaults are 20 tool calls/10 resource reads, or 30/10 for programmer.

- Dispatcher counters are per dispatcher/task. Authorized attempts count before
  forwarding, including calls that fail remotely.
- Scoped-server counters are per server instance/process and shared across tools.
  Invocations reaching a guarded callback count even if that callback fails;
  requests rejected before execution (unknown names/schema failures) do not count.
- Both layers update counters under a lock. Concurrent calls cannot overspend the
  allowance. A failed resource read does not refund its dispatcher allowance.
- `max_steps` bounds turns in the Phase 4.3 loop. The counters here bound tool/resource
  invocations; dollar budgets are enforced separately by the accounting controller.
- Restarting a server or creating another dispatcher requires trusted orchestration.
  A model cannot reset counters through tool arguments. Keep the server scoped too,
  so constructing a fresh client-side dispatcher cannot reset server-side limits.

## Editing or adding permissions

Profiles may narrow permissions within their role's ceiling. To approve a new
capability, the operator must review the tool, update the appropriate code ceiling
and YAML, add authorization tests, and restart the scoped process. Changing YAML
alone cannot cross the current ceiling. Provider/model selection remains separate.

## Tests and remaining work

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_roles.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_role_stdio.py' -v
.venv/bin/python -m unittest discover -s tests -v
```

Ten loader/dispatcher tests cover all profiles, invalid paths/settings, unsafe
YAML and links, immutable policy, forged calls, resource policy, tampered profile
copies, atomic limits, role injection, and rejecting mismatched/unscoped servers. Two real stdio tests exercise all four
role launch paths, exact discovery, allowed reads, control-plane denial, QA write
denial, and server-side limits without the dispatcher. All state is temporary.

Phase 4.3 now implements provider adapters, a bounded task loop, reservations,
idempotent settlement, audit records, and a review/revision hook. See
[task execution and recovery](phase4-orchestrator.md).
The role prompts are not automatically installed as a desktop host's system prompt;
that integration and the final supervised model task remain pending.

Validation result: all 74 tests passed, with no skips. The new/changed Phase 4 modules and tests passed Ruff. No model/provider API was called.
