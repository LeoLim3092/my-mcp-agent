# Phase 2.4 validation

## Automated milestone

From the project root:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_phase2_milestone.py' -v
```

Expected: one test reports `ok`, followed by `OK`.

The test registers real MCP resources/tools, reads both JSON resources through
MCP dispatch, checks live hardware readings and refreshed timestamps, logs fake
usage, and verifies the budget resource updates and survives server recreation.
It uses a temporary SQLite database that is deleted afterward. It makes no paid
model calls and does not change the real ledger or game workspace.

This verifies dispatch, not an MCP transport connection or Inspector UI.
Each resource/tool call has a 10-second timeout. If a restricted execution
environment blocks MCP worker-thread dispatch, run from your normal local terminal.

## Manual Inspector milestone

1. Start Inspector from the project root:

   ```bash
   uv run mcp dev src/my_mcp_agent/server.py
   ```

2. Open the Inspector URL printed by the command and connect to the server.
3. Open **Resources**, list resources, and read `studio://telemetry/hardware`.
   Verify JSON with CPU percentage, memory bytes, and disk bytes. CPU usage must
   be between 0 and 100. A missing Windows mount must report `available: false`.
4. Read hardware again. Its UTC timestamp should advance; usage values may stay
   the same. Compare capacities with local OS tools if needed.
5. Read `studio://telemetry/budget`. Verify valid JSON with today's UTC date,
   decimal-string USD totals, token counts, and budget flags. The first budget
   read creates `studio_ledger.db` if absent; do not assume an existing ledger is empty.
6. Restart the server, reconnect, and read the budget again. Recorded usage should
   persist; totals may change at UTC midnight or if another client logs usage.
7. Record the date and results below, then mark the manual milestone complete in
   `MasterChecklist.md` and matching Inspector tasks in `todo.md`.

Use the automated test for fake usage and over-budget experiments; do not pollute
the real ledger with sample spending. The real ledger contains accounting data
and is ignored by Git. Reading hardware does not create game files.

## Validation record

- Automated milestone: passed during implementation outside the restricted sandbox.
- Manual Inspector checks: pending.
- Manual date/environment/results: not yet recorded.
