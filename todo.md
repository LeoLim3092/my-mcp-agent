# Future validation tasks

Implementation progress is tracked in [MasterChecklist.md](MasterChecklist.md).
A completed implementation checkbox does not mean all validation below has passed.
Leave these tasks unchecked until their expected results have been verified.
Use disposable workspaces/repositories with fake secrets for destructive or security tests.
Record the date, environment, command or MCP inputs, and observed result when completing a task.

## Review findings — 2026-11-03

Logged before remediation. The existing 39 tests passed, but focused disposable-workspace probes confirmed these defects:

- [x] F1 / High: general file tools read an outside file through an existing workspace hard link, and `write_file` changed that outside file. Reject hard links, use descriptor-relative no-symlink reads, and publish writes atomically without following destination links. Add regression tests for read/write/patch and path replacement.
- [x] F2 / High: `run_tests("tests")` fails to import a workspace-root `game.py` from `tests/test_game.py`. Add explicit snapshot import paths while preserving isolated Python startup, and test root and `src/` layouts. Dependency installation stays operator-controlled; do not run workspace install hooks automatically.
- [x] F3 / Medium: execution snapshots omit empty directories, so linting an existing empty directory fails with a missing-path error. Preserve allowed empty/nested directories and test their entry limits.

Still required separately: real stdio/Inspector validation; bounded file/list/Git output; a complete web/DNS deadline; concurrent edits/Git/export handling; budget reservations/idempotency; Phase 4 role authorization. Aggregate cgroup quotas are required before hostile concurrent execution. These are not claimed fixed by F1–F3 remediation.

Remediation: F1 uses `workspace_io.py` for descriptor-relative, no-symlink access,
regular/single-link checks, and atomic file replacement. F2 adds explicit snapshot
root/src import paths after importing the trusted pytest runtime. F3 preserves
allowed directories and applies snapshot entry limits. Six new file-access tests
and three QA/snapshot tests cover the reproduced defects. The suite now has 48 tests.

Remaining boundary: directory-descriptor access does not prevent an OS-level actor
from relocating an already-open directory outside the workspace. Atomic replacement
also does not detect lost updates from concurrent patches; whole export batches
and Git operations need separate concurrency protection.

## Existing automated checks

The current suite has 100 tests: six filesystem tests, six Git tests, six budget
tests, four telemetry tests, one Phase 1 milestone, one Phase 2 milestone,
eighteen Phase 3 tests, six workspace I/O regression tests, ten MCP contract tests, six stdio connection tests, ten role/dispatcher tests, two role-scoped stdio tests, seven accounting tests, five provider tests, eleven task-loop tests, and one offline CLI test. Tests cover direct
functions, MCP dispatch, isolated QA/Blender execution, and the review fixes.

Run the full suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Run only Git tests:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_git_ops.py' -v
```

Tests exercise direct functions, real MCP tool/resource dispatch, initialized
in-memory client/server sessions, and real stdio server subprocesses with temporary
state. The user's selected desktop/launch configuration and Inspector UI remain pending.

## Phase 0 — Server startup and MCP integration

- [ ] Recheck `uv run mcp dev src/my_mcp_agent/server.py` after the recent changes; Inspector connects and all implemented tools appear with correct arguments and descriptions.
- [x] Verify actual server stdio initialization, `workspace_ping`, discovery, and resource reads using a real subprocess with temporary state (`tests/test_client.py`).
- [ ] Validate the user's selected host/launch command on their actual deployment; automated subprocess tests do not configure a desktop application.
- [x] Restart the actual stdio server and verify registrations are not duplicated and existing workspace files remain unchanged (`tests/test_client.py`).
- [ ] Add repeatable startup tests: importing `config.py` and `security.py` creates no directories; server initialization creates a missing workspace and rejects overlapping project/workspace trees.
- [ ] Verify a missing/unwritable workspace produces a clear startup error without modifying an unintended location.

## Phase 1.1 — Path policy

- [ ] Add dedicated `security.py` regression tests for every protected directory, credential filename pattern, and write-protected name, including nested entries and case variations.
- [ ] Confirm allowed absolute workspace paths work, outside absolute paths fail, and sibling directories with a similar name cannot pass containment checks.
- [ ] Verify empty paths, whitespace, `.`, and parent traversal have the documented behavior; root writes must fail.
- [ ] Test external, internal, broken, and chained symlinks; neither reads nor writes may follow them.
- [x] General file I/O and snapshots reject hard links; regression tests confirm read/write/patch cannot access or change an outside hard-linked file. Continue the separate Git boundary review before claiming all operations are safe against hostile local writers.
- [ ] Test concurrent path/symlink replacement using disposable files. Implement and verify safe file-opening practices or OS isolation before claiming protection against these races.
- [ ] Review credential patterns against actual development tools; unknown secret filenames are not automatically detected.

## Phase 1.2 — Filesystem tools

- [ ] In MCP Inspector, create `GDD.md`, list it, read numbered lines, patch one unique block, and read back the expected result.
- [ ] Through MCP, attempt `/etc/passwd`, traversal, `.env`, `.git/config`, and symlink access; each call fails without returning protected contents.
- [ ] Through MCP, verify an invalid call returns a useful tool error and the next valid call still succeeds.
- [ ] Test empty files, LF/CRLF endings, final lines without a newline, and Unicode filenames/content through the MCP client.
- [ ] Test exactly `MAX_FILE_READ_BYTES` and one byte above it, including multibyte UTF-8; oversized reads and patches fail without changing the file.
- [ ] Verify missing files, permission errors, and disappearing directory entries fail clearly without leaking protected data.
- [x] Use atomic replacement for general file writes and test failed publication: existing content remains intact and temporary files are cleaned.
- [ ] Add concurrent patch conflict detection; atomic replacement alone can still lose another writer's changes.
- [x] Test hard-linked files and FIFOs with disposable fixtures; general file writes do not alter outside data, and FIFO reads/writes reject without blocking.
- [ ] Measure large-directory listings and large writes; decide on output, write-size, and disk-usage limits before wider use.

## Phase 1.3 — Git tools

- [ ] Initialize a disposable standalone workspace repository and configure repository-local `user.name` and `user.email`; do not use the MCP server's own repository.
- [ ] Through MCP Inspector, verify `git_status` reports untracked, staged, modified, deleted, and renamed files while omitting protected paths.
- [ ] Verify `git_diff` returns only unstaged changes for the requested file, excludes staged-only changes, and returns no diff for untracked files.
- [ ] Verify filenames containing spaces, Unicode, newlines, leading hyphens, and Git pathspec characters are handled literally and cannot inject arguments or expand the requested scope.
- [ ] Complete the Phase 1 milestone: create `GDD.md` through MCP, review it, stage that specific file manually with `git add -- GDD.md`, and call `git_checkpoint` on a new test branch. Verify the commit contents and unchanged `main` history.
- [ ] Through MCP, confirm current-feature-branch commits work and `main`, `master`, invalid branch names, empty messages, and no staged changes are rejected.
- [ ] Add tests for a first commit in an unborn repository, detached HEAD, merge/rebase/cherry-pick/revert states, unresolved conflicts, index locks, and missing commit identity.
- [ ] Test staged sensitive-file deletions and renames into/out of protected paths; checkpoint must reject protected changes before changing branches.
- [ ] Verify linked worktrees, submodules, symlinked metadata, and external Git metadata are rejected as intended.
- [ ] Verify external diff, text-conversion commands, filesystem monitors, hooks, signing, and inherited Git configuration cannot run unintended commands or redirect operations.
- [ ] Simulate Git absence, timeout, and commit failure; errors must be clear. Document that a failed commit after branch creation may leave the new branch checked out.
- [ ] Test large diffs/status output and concurrent index/branch changes; decide on output limits and serialization before multiple clients use Git tools simultaneously.
- [ ] Review repository-local configuration and attributes as an execution boundary; these tools are not an OS sandbox for an attacker-controlled repository.

## Later phases — Validation to schedule when implemented

- [ ] Phase 2: verify hardware resource responses through MCP, ledger persistence, timezone/day rollover, concurrent logging, malformed usage, and exact budget boundaries. Verify every model call is gated; recording spending afterward cannot prevent an already incurred charge.
- [x] Phase 3: verify QA/Blender execution cannot read server files or credentials, write outside allowed mounts, or use disallowed network access; test timeout/process cleanup. See the Phase 3 validation guide for tested boundaries and remaining hardening.
- [x] Phase 3: verify web fetching blocks disallowed internal destinations, including redirects and DNS changes; bound response size and socket/read time. A hard OS DNS deadline remains pending below.
- [x] Phase 3: verify shared memory includes only explicitly approved documents, applies secret-path policy, and rejects symlinks. Operators must keep secrets out of approved document contents.
- [ ] Phase 4: test the real desktop/client integration and server/dispatcher authorization for every role. Editing prompts or YAML must not grant extra tools.
- [ ] Phase 4: run an end-to-end task with budget preflight, authorized tools, usage recording, failures, and restart recovery.

## Phase 2.2 — Hardware telemetry follow-up

- [ ] Read `studio://telemetry/hardware` through MCP Inspector; verify JSON MIME type, fresh timestamps, CPU percentages, RAM bytes, and disk bytes.
- [ ] Compare system disk/RAM readings with local OS tools; compare Windows C: disk space when `/mnt/c` is mounted under WSL.
- [ ] Verify unavailable Windows mounts and disk permission errors are reported as unavailable rather than zero capacity.

Automated hardware tests: `.venv/bin/python -m unittest discover -s tests -p 'test_telemetry.py' -v`. Four tests cover deterministic sampling, missing/present Windows mounts, disk errors, JSON serialization, and registration. Live sampling was also checked during implementation.

## Phase 2.3 — Usage ledger follow-up

- [ ] In MCP Inspector, log fake usage against a disposable ledger and read `studio://telemetry/budget`; confirm exact decimal strings and token totals.
- [ ] Through MCP, test invalid token/cost inputs and over-budget errors. Verify over-budget usage persists and never retry the same recorded call.
- [x] Add durable request IDs and idempotent settlement for the orchestrator; keep uncertain provider calls held and avoid automatic request retries.
- [ ] Extend raw operator `log_task_usage` with idempotency if that separate API will be retried automatically; it currently remains non-idempotent.
- [ ] Verify database lock timeout, disk-full/unwritable errors, recovery, backup permissions, and migration strategy before storing important usage history.
- [x] Add orchestrator pre-call reservations and trusted provider-usage settlement; model roles cannot access accounting. Cost calculation uses operator rates, not model-authored prices. Raw post-task logging remains operator-only and does not itself gate calls.
- [ ] Confirm UTC budget days are the intended policy; add a configurable timezone only if local-day reporting is required.

Budget tests: `.venv/bin/python -m unittest discover -s tests -p 'test_budget.py' -v`. Six tests cover persisted/exact totals, limit boundaries, invalid inputs, UTC rollover, concurrent writes, JSON resource output, and registration. Runtime `studio_ledger.db*` files are excluded from Git.

## Phase 2.4 — Milestone status

- [x] Automated MCP dispatch test in `tests/test_phase2_milestone.py` passes using live hardware and a temporary ledger. Verified outside the restricted sandbox after its thread dispatch timed out inside it.
- [x] Document test commands, expected results, and manual Inspector steps in [docs/phase2-validation.md](docs/phase2-validation.md).
- [ ] Complete and record manual Resources-tab checks for both telemetry URIs using that guide; then update the Phase 2 milestone checkbox.

## Phase 3 — Implementation and validation complete

- [x] Implement isolated Ruff/pytest, public documentation fetching, Blender execution/validated exports, and approved architecture memory.
- [x] Run real Ruff and pytest success/failure cases in Bubblewrap with no network and no host home directory.
- [x] Verify cleared secret environment, blocked host path access, read-only inputs, timeout cleanup, and bounded output.
- [x] Verify snapshots omit protected files, Git metadata, symlinks, hard links, and special files.
- [x] Verify public-web policy, private/metadata addresses, redirect checks, checked-IP sockets, text conversion, response sizes/types, and compressed-response rejection.
- [x] Fetch live Python pathlib documentation successfully over HTTPS.
- [x] Run verified Blender 4.5.3: generate cube, inspect six polygons, export and reload `.blend`, report Python errors, and reject symlink exports.
- [x] Verify MCP tool/resource dispatch and explicit/dynamic/bounded architecture memory.
- [x] Add [Phase 3 setup and validation](docs/phase3-validation.md) and an official-checksum portable Blender installer. Runtime binaries remain ignored by Git.
- [ ] Before hostile multi-tenant execution, add aggregate cgroup memory/PID/disk quotas and stronger kernel-level restrictions; current limits are per process/user and namespaces share the host kernel.
- [x] Harden general file I/O against symlink replacement using descriptor-relative traversal and atomic replacement; add simulated ancestor/final-symlink regression tests.
- [ ] Protect concurrent Blender publication, Git operations, and local directory relocation; descriptor-relative file I/O and snapshot reads do not solve every hostile local-writer case.
- [ ] Add a hard deadline for OS DNS resolution; current socket/read timeouts do not bound synchronous resolver calls.
- [ ] Optionally add a documentation-domain allowlist for deployments that need narrower outbound access.

Phase 3 tests: `.venv/bin/python -m unittest discover -s tests -p 'test_phase3.py' -v`.
The full suite also runs all prior Phase 1/2 tests. Live web fetching was tested separately;
repeatable web tests use mocked public responses. See the guide for runtime prerequisites.

## Leo revision point before Phase 4

This checkpoint contains the F1–F3 review fixes, nine regression tests, corrected
validation records, and Blender MCP limitations. The foundation now has 48 passing
tests; real client transport validation and the separately listed requirements
remain open. The checkpoint is recorded in `MasterChecklist.md` immediately before
Phase 4 and in the associated revision commit.

## MCP input/output contract revision

- [x] Publish valid input and output schemas for all 13 tools; replace bare dictionary result annotations with explicit typed contracts.
- [x] Publish strict token counts, path/string lengths, nonblank identifiers, script bounds, and decimal-string cost constraints.
- [x] Enforce a 1 MB encoded write limit before modifying files or creating parent directories; patch outputs use the same limit.
- [x] Preserve expected tool errors, especially the saved-log/no-retry over-budget warning; keep unexpected crash details server-side.
- [x] Validate success/error responses using a real initialized MCP client/server session over in-memory transport.
- [x] Add ten contract tests; full suite has 58 passing tests. See [MCP tool contracts](docs/mcp-tool-contracts.md).
- [ ] Complete production stdio/desktop/Inspector checks; in-memory protocol coverage does not validate those deployment paths.
- [ ] Add logging idempotency before safe automatic retries; an error flag does not imply side effects were rolled back.

## Phase 4.1 — Provider-neutral connection

- [x] Add provider-independent stdio client/diagnostics and trusted example connection settings.
- [x] Exercise the actual server subprocess with temporary state: MCP initialization, tools/resources, live telemetry/budget, memory, and restart preservation.
- [x] Document native/WSL host examples and the separation of MCP connections, roles, model assignments, and future provider adapters in [Phase 4 provider-neutral setup](docs/phase4-provider-neutral.md).
- [ ] Choose and connect the user's preferred host/model; desktop/Inspector UI checks remain pending.
- [ ] Implement Phase 4.2 role authorization and Phase 4.3 provider adapters/orchestration. The diagnostic client has no role policy or LLM integration yet.

Connection tests: `.venv/bin/python -m unittest discover -s tests -p 'test_client.py' -v`.

Phase 4.1 validation record: all five connection tests passed. The full suite has 63 tests; no model provider was called, and desktop/Inspector validation is still pending.

## Phase 4.2 — Roles and authorization

- [x] Add immutable provider-neutral writer/programmer/artist/QA YAML profiles with safe named loading, permission ceilings, and bounded call settings.
- [x] Enforce every model tool/resource request in a trusted dispatcher, including forged names, resource traversal, and attempted role changes in arguments.
- [x] Add role-scoped server launch and registration, so raw MCP calls cannot bypass permissions or server-process call limits.
- [x] Keep usage logging, budget resources, role selection, and process launch outside all model role capabilities.
- [x] Add nine role/dispatcher tests and two real-stdio role tests, with temporary state and no provider calls. See [role setup](docs/phase4-roles.md).
- [x] Implement the Phase 4.3 provider adapters, model-turn limit, task loop, budget reservations/idempotent settlement, metadata audit records, and review/revision hook.
- [ ] Manually connect the chosen host with a scoped launch command. An unscoped desktop connection retains operator capabilities; prompts alone do not restrict it.

Phase 4.2 validation record: all 74 tests passed, including actual stdio role enforcement and existing isolated Blender regressions. New/changed Phase 4 modules and tests passed Ruff. Manual host/model testing remains deferred until Phase 4 is complete, as requested.

## Phase 4.3 — Task loop and accounting complete; live-model acceptance pending

- [x] Implement nonstreaming Chat Completions-compatible and native Ollama adapters with explicit model/endpoint/rates/tool capability, no implicit provider choice, no HTTP retries/redirects, bounded context/output, and strict usage handling.
- [x] Verify exact role-scoped server capabilities, enforce model turns and tool/resource allowances, and expose approved resources only through checked calls.
- [x] Reserve budget atomically before requests, settle known usage idempotently, retain uncertain holds across UTC days, and stop on cost/reservation overruns.
- [x] Add durable task IDs and hashed tool-call claims; forbid silent task/request/tool replay. Provide status inspection and explicit operator settlement/release APIs.
- [x] Preserve old ledger rows during schema migration and expose reserved/available budget amounts.
- [x] Add metadata-only audit events and review/revision decisions. Default real tasks to `needs_review`; the offline ping demo has a demo-only approval callback.
- [x] Test seven accounting cases, five provider cases, eleven real-MCP task-loop cases, and one offline CLI/status case, plus server-scope matching. Combined suite: 100 tests.
- [ ] Choose an actual provider/model, fill accurate rates and credentials, and validate a supervised live task. No paid/model-service request was made during automated validation.
- [ ] Complete the selected desktop/Inspector acceptance checks. Manual pipeline testing remains deferred at the user's request until implementation is ready.
- [ ] Add more protocol adapters or provider-specific billing (cache tiers/extra fees) only when needed; current cost calculation is a configured token-rate estimate, not an invoice guarantee.
- [ ] Add full conversation restoration/resume only with explicit treatment of uncertain side effects; current recovery deliberately inspects/reconciles without automatic replay.
- [ ] Add actual visual/game-engine review tooling or a separately budget-controlled reviewer agent as needed; the current review callback is an integration boundary, not an automatic quality guarantee.

Guide: [Phase 4 task execution and recovery](docs/phase4-orchestrator.md).
Offline command: `.venv/bin/python -m my_mcp_agent.orchestrator --demo --role qa`.

Phase 4 review follow-up: inspect execution `passed`, exit-code, and timeout fields independently of MCP transport success; include failed operation names in review evidence. The offline demo approves only a successful ping, not an error response.

Phase 4 integration review: raise the default MCP request timeout to 45 seconds (above the 30-second execution timeout) and test that relationship. This prevents an otherwise valid long-running QA/Blender command from timing out first at the client.

Phase 4.3 final validation (2026-11-05): full 100-test suite passed with no skips;
Ruff passed for changed modules/new tests. No paid provider calls and no real game
file modifications occurred. The tool/resource format regression discovered during
review was corrected and covered by the approved-resource pipeline test.
