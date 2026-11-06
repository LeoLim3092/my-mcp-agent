# Phase 4.3: provider-neutral task execution

The task runner connects an operator-selected role to its scoped MCP server,
translates model tool calls through `RoleDispatcher`, and accounts for each model
request. No single model/provider is mandatory. There are two implemented HTTP
protocol adapters: Chat Completions-compatible endpoints and native Ollama chat.
Other provider protocols require an additional adapter; they are not automatically supported.

## Offline pipeline test

```bash
.venv/bin/python -m my_mcp_agent.orchestrator --demo --role qa
```

The deterministic demo makes no HTTP/model call. It starts a QA-scoped MCP server,
checks its scope, reserves zero USD, calls `workspace_ping`, records zero-cost
usage, and produces a final response. A demo-only review callback approves this
connectivity check. It does not approve real game changes or asset quality.

Expected output includes a generated `task_id`, `status: "completed"`, and two
model-loop steps. Game files are not changed. Startup may create the workspace,
and the normal runtime ledger gains task/audit/zero-cost usage records.

## Run a configured model

Keep provider configuration in the trusted repository, outside the writable game
workspace. Select model, endpoint, declared tool capability, rates, output/context
limits, and a per-request reservation. Secrets are referenced by environment
variable name; never put API keys in prompts, YAML roles, connection args, or JSON.

### Local Ollama

Edit `config/provider.ollama.example.json` to name an installed tool-capable model.
Zero USD rates mean local inference is not charged to the API-spend ledger; they
do not mean local compute has no resource cost. Model installation/service startup
is operator-controlled and is not performed by this tool.

```bash
.venv/bin/python -m my_mcp_agent.orchestrator \
  --role qa \
  --provider-config config/provider.ollama.example.json \
  --task "Review the game files and report relevant test results."
```

### Hosted or local Chat Completions-compatible API

Edit `config/provider.chat-completions.example.json`. Its rate/reservation
placeholders intentionally fail validation until replaced. Use actual rates for
your provider/account/model and an appropriate request allowance; no current model
prices are assumed. Export the referenced credential in your terminal separately.
Then run the same command with this configuration path and an authorized task.

Remote endpoints require HTTPS; HTTP is restricted to literal loopback/localhost.
The configured endpoint is trusted executable/network authority, not a URL a model
can choose. Environment proxies, redirects, automatic retries, and streaming are
disabled. Requests have a total configured timeout; responses must be uncompressed
and at most 2 MB. Choose `max_tokens` instead of `max_completion_tokens` only for a
compatible endpoint that requires that parameter.

The adapter sends tools as function schemas and normalizes usage/tool replies.
Tool support, accepted schemas, completion parameters, model behavior, context
limits, and usage semantics must be verified for the selected model. A capability
flag is an operator declaration, not a live compatibility certification. Missing
usage, unsupported/truncated responses, or malformed provider results stop the task
and retain the reservation for reconciliation rather than inventing usage.

Reference formats: [official Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
and [official Ollama API](https://github.com/ollama/ollama/blob/main/docs/api.md).

## Bounded task loop and permissions

1. Verify the connected server's exact tool/resource set matches the assigned role.
2. Claim a unique task ID in SQLite before any provider request.
3. Prepare messages using the trusted role system prompt and the user's task.
4. Advertise only allowed MCP tools plus `read_studio_resource`, whose URI schema
   lists only the role's permitted resources. Every resource call is still checked.
5. Validate context/credentials and reserve budget before sending each model turn.
6. Settle reported usage before executing model-selected tools.
7. Claim each tool-call ID durably, execute through the dispatcher, and return a
   bounded result to the model. Tool calls execute sequentially, not in parallel.
8. Stop on model-turn/call limits, budget problems, uncertain outcomes, or final text.

`max_steps` from the role now bounds model turns, including revision turns.
Role tool/resource allowances remain enforced at both dispatcher and server.
Task text is capped at 16 KB and each forwarded tool result at 16 KB. Large results
are marked truncated; the runner does not silently summarize or discard history.
The provider request must fit its configured byte/context allowance.

The default CLI starts a fresh role-scoped stdio process for each run. The default
MCP request timeout is 45 seconds, longer than the 30-second tool execution limit;
operator configuration can adjust it for slower environments. It does not
give the model an operator session, API credential, launch configuration, or usage
logging tool. Attempts to request forbidden tools/resources return denied feedback.
The runner inspects `passed`, exit code, and timeout fields as well as the MCP
error flag; a failed test or Blender execution is recorded as failed evidence.
Tool failures can be returned for correction, but ambiguous transport failures
stop execution rather than automatically retrying side effects.

## Review and revision

Real model tasks with final text return **`needs_review`** by default. Final text is
not proof that a feature works or an asset looks good. The CLI does not automatically
approve production work.

Trusted Python code can inject an async reviewer:

```python
async def reviewer(context):
    # context has task, candidate answer, successful_tools, and failed_tools.
    # Obtain actual evidence/operator feedback before approving.
    return ReviewDecision(approved=False, feedback="Add the missing validation evidence.")

runner = TaskRunner(adapter, dispatcher, reviewer=reviewer)
```

Approval ends the task as `completed`; revision feedback goes back into the same
bounded loop without expanding permissions. Without a reviewer, it stops at
`needs_review`. A reviewer requiring model calls must use the same budget-controlled
runner/accounting path. The callback is an integration hook, not a built-in visual
reviewer or an automatically trusted judge. Game-engine/visual review tools remain
future additions. No automatic undo or transactional rollback of game edits is implied.

## Budget reservations and accounting

`accounting.py` adds durable reservation, task, tool-claim, and audit tables to the
existing ledger. Legacy token records are preserved; migration is serialized.

Before a request, an immediate transaction checks recorded UTC-day spend plus
all unresolved holds. Concurrent callers cannot reserve the same available money.
The adapter also rejects allowances below a conservative estimate using request
UTF-8 bytes as the input token allowance plus the enforced output cap. This is a
conservative approximation, not a universal tokenizer or invoice guarantee.

Usage cost is calculated from provider-reported input/output token counts and
operator-configured per-million-token rates, rounded upward to 12 decimal places.
Rates must account for the chosen service. Cached/discounted tokens, separate
fees, hidden billing, other applications using the same key, or incorrect pricing
can make this accounting differ from the provider invoice. Local safeguards are
not a provider-enforced spending limit.

A known usage result is settled exactly once under its request ID; duplicate
settlement with identical values returns the original log ID. Conflicting duplicate
values are rejected. Settlement releases the hold and records actual usage even
when it exceeds the reservation/daily limit; the runner then stops before further
model/tool calls. Costs are attributed to the request's UTC start day.

Budget JSON now also includes `reserved_usd` and `available_usd`:

- `remaining_usd`: daily cap minus recorded spend, clamped to zero.
- `reserved_usd`: all unresolved reservations, including prior UTC days.
- `available_usd`: remaining spend capacity minus unresolved holds, clamped to zero.

Timeouts, cancellation, missing usage, or lost responses keep the hold. Stale holds
are not automatically expired: an expired timer is not evidence that no charge
occurred. Raw `log_task_usage` calls remain non-idempotent; orchestrator settlement
is the separate idempotent path and is not exposed to model roles.

## Crash/restart recovery

```bash
.venv/bin/python -m my_mcp_agent.orchestrator --status TASK_ID
```

The CLI prints the task ID to stderr before starting, so it remains available if
the process is interrupted. Status returns metadata, request states, hashed
tool-call claims, and audit events.
Prompts, tool arguments/results, model answers, and credentials are not persisted
in these audit tables. Default task IDs are opaque. Treat task identifiers, model
names, and spending records as private operational data too.

A previously claimed task ID cannot be run again, even after failure. A tool-call
ID cannot be executed twice within a task. These are application identities, not
provider-side idempotency guarantees. Choosing a new task ID starts new work and
can repeat semantic side effects; do not do so to bypass an uncertain state.

For an uncertain model request, the operator investigates provider records and
then uses the trusted Python accounting API:

```python
# If actual usage/cost is known, settlement is idempotent:
accounting.settle("TASK_ID:TURN", input_tokens=100, output_tokens=20, cost_usd="0.001")

# Only after confirming the provider did not bill the request:
accounting.release_confirmed_unbilled("TASK_ID:TURN")
```

For a started/uncertain tool invocation, inspect the actual workspace/Git/export
state before deciding what new task is safe. There is no automatic tool replay,
conversation restoration, or transparent resume after a crash. A task may remain
`running` after process death; its durable request/tool states are the recovery
source of truth. Inspection/reconciliation does not automatically mark the whole
original task reviewed or complete.

## Tests and remaining manual milestone

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_accounting.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_providers.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_orchestrator.py' -v
.venv/bin/python -m unittest discover -s tests -v
```

Automated coverage uses mocked provider responses and real role-scoped MCP
subprocesses, with temporary files/ledgers. It covers both protocol adapters,
known usage, reservations, concurrency, migration, exact settlement, day rollover,
unknown outcomes, cancellation, role denials, resource access, turn limits,
review/revision, duplicate identities, and lost tool responses.

No paid request or live selected-model compatibility test has been made. Phase 4.4
still needs the chosen host/model setup, desktop/Inspector checks, and a supervised
live-model task with recorded limitations. Completing the automated pipeline does
not certify every model or replace visual/game-engine validation.

Implementation validation includes 100 tests in the combined suite, with no paid provider calls. The live-provider and selected-host acceptance milestone remains pending.

## Validation record — 2026-11-05

- Full suite: 100 tests passed, no skips, including prior isolated Blender checks.
- Changed implementation modules and new tests: Ruff passed.
- Providers: mocked HTTP only; actual MCP stdio processes used temporary state.
- Offline CLI: completed ping-only task and read its persisted status after restart.
- Review evidence distinguishes MCP success from failed QA/Blender execution.
- The default MCP request timeout now exceeds the execution timeout.
- Selected live-model and desktop/Inspector acceptance: pending.

Current adapters handle text and function calls. They do not translate image/audio
messages, implement streaming/background provider jobs, or visually review Blender
assets. Those require additional adapters or review tools.
