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

The current suite has 48 tests: six filesystem tests, six Git tests, six budget
tests, four telemetry tests, one Phase 1 milestone, one Phase 2 milestone,
eighteen Phase 3 tests, and six workspace I/O regression tests. Tests cover direct
functions, MCP dispatch, isolated QA/Blender execution, and the review fixes.

Run the full suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Run only Git tests:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_git_ops.py' -v
```

Tests exercise direct functions and real MCP tool/resource dispatch. They do not
exercise a full client transport session or Inspector UI; those checks remain pending.

## Phase 0 — Server startup and MCP integration

- [ ] Recheck `uv run mcp dev src/my_mcp_agent/server.py` after the recent changes; Inspector connects and all implemented tools appear with correct arguments and descriptions.
- [ ] Start through the production stdio command, `uv run mcp run src/my_mcp_agent/server.py`; a real MCP client initializes and can call `workspace_ping` without protocol errors.
- [ ] Restart the server and verify registrations are not duplicated and existing workspace files remain unchanged.
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
- [ ] Add idempotency keys before introducing automatic logging retries; current repeated calls create repeated records.
- [ ] Verify database lock timeout, disk-full/unwritable errors, recovery, backup permissions, and migration strategy before storing important usage history.
- [ ] Enforce trusted usage reporting and pre-call budget reservations in the orchestrator; the current post-task logger cannot stop costs already incurred or verify caller-supplied cost.
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
