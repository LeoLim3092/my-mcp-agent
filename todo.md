# Future validation tasks

Implementation progress is tracked in [MasterChecklist.md](MasterChecklist.md).
A completed implementation checkbox does not mean all validation below has passed.
Leave these tasks unchecked until their expected results have been verified.
Use disposable workspaces/repositories with fake secrets for destructive or security tests.
Record the date, environment, command or MCP inputs, and observed result when completing a task.

## Existing automated checks

The current suite contains six filesystem tests and six Git tests. It covers basic
UTF-8 file operations, patch rejection, protected paths, internal symlinks, read
limits, binary rejection, tool registration, staged-only commits, branch protection,
hook suppression, repository boundaries, and inherited Git overrides.

Run the full suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Run only Git tests:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_git_ops.py' -v
```

These tests call tool functions directly. They do not exercise a full MCP client
session. Real MCP tool schema generation was also checked separately during development.

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
- [ ] Review hard links to outside files: document the current limitation and select an isolation or file-opening policy before treating the workspace as safe for hostile local writers.
- [ ] Test concurrent path/symlink replacement using disposable files. Implement and verify safe file-opening practices or OS isolation before claiming protection against these races.
- [ ] Review credential patterns against actual development tools; unknown secret filenames are not automatically detected.

## Phase 1.2 — Filesystem tools

- [ ] In MCP Inspector, create `GDD.md`, list it, read numbered lines, patch one unique block, and read back the expected result.
- [ ] Through MCP, attempt `/etc/passwd`, traversal, `.env`, `.git/config`, and symlink access; each call fails without returning protected contents.
- [ ] Through MCP, verify an invalid call returns a useful tool error and the next valid call still succeeds.
- [ ] Test empty files, LF/CRLF endings, final lines without a newline, and Unicode filenames/content through the MCP client.
- [ ] Test exactly `MAX_FILE_READ_BYTES` and one byte above it, including multibyte UTF-8; oversized reads and patches fail without changing the file.
- [ ] Verify missing files, permission errors, and disappearing directory entries fail clearly without leaking protected data.
- [ ] Test interrupted writes and concurrent edits. Decide whether atomic replacement and conflict detection are required; current writes can truncate before completion and patches can overwrite concurrent edits.
- [ ] Test existing hard links and special files in an isolated environment; writes must not alter outside data or block indefinitely.
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
- [ ] Phase 3: verify QA/Blender execution cannot read server files or credentials, write outside allowed mounts, or use disallowed network access; test timeout/process cleanup.
- [ ] Phase 3: verify web fetching blocks disallowed internal destinations, including redirects and DNS changes; bound response size and request time.
- [ ] Phase 3: verify shared memory includes only explicitly approved documents and never exposes credentials or follows symlinks.
- [ ] Phase 4: test the real desktop/client integration and server/dispatcher authorization for every role. Editing prompts or YAML must not grant extra tools.
- [ ] Phase 4: run an end-to-end task with budget preflight, authorized tools, usage recording, failures, and restart recovery.
