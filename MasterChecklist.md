# Solo Game Studio MCP Architecture — Master Checklist

**Sensitivity tags:** `[PRIVACY]` may contain or expose private data; `[INTEGRITY]` / `[CRITICAL INTEGRITY]` protects trusted code or settings; `[HIGH PRIVILEGE]` can modify files or Git state; `[CRITICAL PRIVILEGE]` can execute code; `[CONDITIONAL PRIVACY]` depends on contents. Tags describe the planned working implementation.

## Architectural Principle
- **Layer 1: Role-Based Agents (The Brains):** Client-side personas (Game Designer, Lead Programmer, 3D Artist, QA Tester) with specific system prompts and restricted tool access.
- **Layer 2: Capability-Based MCP Servers (The Hands):** Stateless, strictly-typed Python tools (`@mcp.tool()`) and data streams (`@mcp.resource()`) exposed via `MCPServer`.
bui
---

## Phase 0: Modular Project Structure (Preparation)
- [✓] **Create modular directory layout inside `src/my_mcp_agent/` [INTEGRITY]:**
  - [✓] `server.py` [INTEGRITY] (Main `MCPServer` entry point, replacing `hello_mcp.py` [INTEGRITY])
  - [✓] `config.py` [CRITICAL INTEGRITY] (Workspace paths, budget caps, size limits, and protection rules; no directory creation on import)
  - [✓] `security.py` [CRITICAL INTEGRITY] (`validate_path()` and `SandboxViolationError`; enforces file-access policy)
  - [x] `ledger.py` [CRITICAL INTEGRITY] [PRIVACY] (SQLite initialization, exact-decimal usage accounting, and UTC daily summaries)
  - [x] `execution.py` [CRITICAL PRIVILEGE] (filtered snapshot copying and fail-closed Bubblewrap runner)
  - [x] `workspace_io.py` [CRITICAL INTEGRITY] (descriptor-relative no-symlink access, hard-link refusal, and atomic file replacement)
  - [✓] `tools/` [INTEGRITY] directory (`__init__.py` [INTEGRITY], `filesystem.py` [HIGH PRIVILEGE] [PRIVACY], `git_ops.py` [HIGH PRIVILEGE] [PRIVACY], `qa_runner.py` [CRITICAL PRIVILEGE], `external.py` [CRITICAL PRIVILEGE], `budget.py` [INTEGRITY])
  - [✓] `resources/` [INTEGRITY] [PRIVACY] directory (`__init__.py` [INTEGRITY], `telemetry.py` [INTEGRITY] [PRIVACY], `memory.py` [PRIVACY])
- [✓] **Verify entry point:** Run `uv run mcp dev src/my_mcp_agent/server.py` and confirm it loads in the MCP Inspector (`http://localhost:6274`).

---

## Phase 1: Core File & Workspace Server (The Foundation)
*Goal: Give Writing and Coding agents safe read/write/version-control access without risking the host OS.*

- [✓] **1. Define Workspace Policy and Build the Path Validator**
  - [✓] Define workspace [PRIVACY] [INTEGRITY] in `config.py` [CRITICAL INTEGRITY]: `ALLOWED_WORKSPACE = (Path.home() / "game_workspace").resolve()`.
  - [✓] Keep trusted MCP code and `studio_ledger.db` [INTEGRITY] [PRIVACY] outside the game workspace.
  - [✓] Create the workspace during `server.py` [INTEGRITY] startup and reject overlapping workspace/project trees; importing configuration creates no directories.
  - [✓] Define protected directory names, blocked read/write filename patterns, and write-protected settings in `config.py` [CRITICAL INTEGRITY].
  - [✓] Implement `validate_path(rel_path: str, *, operation: Literal["read", "write"] = "read") -> Path` and `SandboxViolationError` in `security.py` [CRITICAL INTEGRITY].
  - [✓] Reject paths outside the workspace, parent traversal, symlinks, protected entries, and attempts to replace/delete the workspace root; provide no protection-bypass parameter.
  - [✓] Check read/write policy behavior and startup initialization using a temporary workspace.
  - Path validation is a file-access policy, not an OS execution sandbox; concurrent path replacement requires safe file-opening practices.
- [✓] **2. Implement File I/O Tools (`tools/filesystem.py` [HIGH PRIVILEGE] [PRIVACY])**
  - [✓] `list_directory(rel_path: str)`: Returns a sorted immediate-child file list (directory names end with `/`) inside the workspace; validate every child before displaying or descending into it.
  - [✓] `read_file(rel_path: str)`: Reads UTF-8 text/code files and returns content with line numbers.
  - [✓] `write_file(rel_path: str, content: str)`: Creates parent folders through directory descriptors and atomically replaces regular, single-link files; rejects hard links and symlinks.
  - [✓] `patch_file(rel_path: str, target_snippet: str, replacement: str)`: Replaces specific code blocks without rewriting entire files (token optimization).
  - [✓] Import `validate_path` from `security.py` [CRITICAL INTEGRITY]; use `operation="write"` for every mutation and enforce `MAX_FILE_READ_BYTES` for reads.
- [✓] **3. Implement Git Safety Tools (`tools/git_ops.py` [HIGH PRIVILEGE] [PRIVACY])**
  - [✓] `git_status()`: Returns short Git status inside `ALLOWED_WORKSPACE`, omitting paths blocked by read policy.
  - [✓] `git_diff(file_path: str)`: Returns unstaged changes for review before committing.
  - [✓] `git_checkpoint(branch_name: str, message: str)`: Commits already staged, policy-approved changes on the current or a new feature branch; blocks `main`/`master` and switching to another existing branch. Does not stage files automatically.
  - [✓] Require a standalone workspace-root repository; disable hooks, signing, external diff/text conversion, and inherited Git overrides; apply a 30-second command timeout.
  - [✓] Verify Git behavior in temporary repositories, including staged-file protection and branch enforcement.
- [✓] **4. Phase 1 Milestone Test**
  - [✓] Test creating `GDD.md` [CONDITIONAL PRIVACY] via `write_file` in MCP Inspector.
  - [✓] Verify `validate_path` raises an error when attempting to read `/etc/passwd` [HOST INFORMATION — DENY ACCESS].
  - [✓] Commit `GDD.md` [CONDITIONAL PRIVACY] to a test branch using `git_checkpoint`.

---

## Phase 2: System & Resource Telemetry (The Guardrails)
*Goal: Track hardware health and API token budgets deterministically in Python.*

- [x] **1. Install Telemetry Dependencies**
  - [x] Run `uv add psutil` (installed 7.2.2; import and CPU/RAM queries verified).
- [x] **2. Expose Hardware Telemetry (`resources/telemetry.py` [INTEGRITY] [PRIVACY])**
  - [x] Implement `@mcp.resource("studio://telemetry/hardware")`: Return JSON with free WSL/Windows disk space (`shutil.disk_usage`), available RAM, and CPU load (`psutil`).
- [x] **3. Build the Token & Cost Ledger (`resources/telemetry.py` [INTEGRITY] [PRIVACY] & `tools/budget.py` [INTEGRITY])**
  - [x] Initialize a local SQLite database (`studio_ledger.db` [INTEGRITY] [PRIVACY]) using `sqlite3` in `ledger.py` [CRITICAL INTEGRITY] [PRIVACY]; initialized on first read/log, with no import-time database writes.
  - [x] Create table `token_logs (id, timestamp, agent_role, model, input_tokens, output_tokens, cost_usd)`.
  - [x] Implement `@mcp.resource("studio://telemetry/budget")`: Return today's UTC cumulative spend vs. `DAILY_BUDGET_USD`, token totals, remaining budget, and exhaustion/exceeded flags. USD values are decimal strings.
  - [x] Implement `@mcp.tool() log_task_usage(...)`: Accepts explicit decimal-string USD cost, records usage in a serialized transaction, and raises a circuit-breaker error after committing over-budget usage. Exactly reaching the limit marks exhaustion; exceeding it raises an error. Do not retry recorded logs; retry deduplication is not implemented.
  - [x] Test persistence, decimal totals, invalid input, UTC rollover, concurrent writes, budget boundaries, and MCP registration with temporary databases.
  - Accounting is post-task reporting, not a model execution gate. Trusted orchestrator preflight/reservations and authenticated usage reporting remain Phase 4 work.
- [ ] **4. Phase 2 Milestone Test**
  - [x] Add and pass `tests/test_phase2_milestone.py`: live JSON resources through MCP dispatch, refreshed hardware timestamps, temporary usage logging, budget updates, and persistence.
  - [x] Document automated and manual steps in `docs/phase2-validation.md`.
  - Inspector verification remains pending; automated dispatch does not replace the manual connection test.
  - [ ] Query `studio://telemetry/hardware` and `studio://telemetry/budget` in the MCP Inspector "Resources" tab and verify live JSON output.

---

## Phase 3: Dev, QA & External Tooling (The Heavy Lifters)
*Goal: Equip Coding, Research, and 3D Artist agents with execution bridges.*

- [x] **1. Build the QA & Linter Runner (`tools/qa_runner.py` [CRITICAL PRIVILEGE])**
  - [x] `run_linter(rel_path: str)`: Runs `ruff check` or game engine script validation with a strict `timeout=30`s, returning stdout/stderr for self-debugging.
  - [x] `run_tests(test_target: str)`: Runs isolated `pytest` with explicit workspace root/src imports on a snapshot preserving empty directories; returns exit code, pass/fail, bounded stdout/stderr, and timeout status.
  - [x] Isolate executed tests from trusted server files, credentials, and unrestricted network access; path validation alone does not constrain executed code.
- [x] **2. Build the Web Documentation Fetcher (`tools/external.py` [CRITICAL PRIVILEGE])**
  - [x] Install `httpx`, `httpcore`, `beautifulsoup4`, `markdownify`, `ruff`, and `pytest`; lock dependencies.
  - [x] `fetch_web_docs(url: str)`: Fetches public HTTP(S) docs, strips HTML boilerplate, and returns Markdown; validates DNS/redirect destinations, pins checked IPs, and caps uncompressed responses at 2 MB.
- [x] **3. Build the Headless Blender Bridge (`tools/external.py` [CRITICAL PRIVILEGE])**
  - [x] `run_blender_script(script_content: str, blend_file: str | None)`: Reads optional workspace `.blend` inputs [CONDITIONAL PRIVACY] and executes a temporary script in isolated headless Blender; validate polygons and write assets under `/output`, then publish supported outputs to `assets/generated/` only on success.
  - [x] Run Blender scripts in an isolated environment with restricted filesystem/network access and no server credentials.
- [x] **4. Build Shared Studio Memory (`resources/memory.py` [PRIVACY])**
  - [x] Implement `@mcp.resource("studio://memory/architecture")`: Dynamically concatenates only approved `MEMORY_DOCUMENTS` (default `GDD.md`, `ARCHITECTURE.md`, `CODING_STANDARDS.md`) [CONDITIONAL PRIVACY], applying path and total-size limits.
- [x] **5. Phase 3 Milestone Test**
  - [x] Run real Ruff/pytest checks, fetch the public Python pathlib documentation, and verify Blender cube polygon count, export/reload, error reporting, and shared MCP tool/resource dispatch.
  - [x] Verify isolated host paths/environment/network, read-only inputs, hard-link/symlink filtering, output truncation, timeouts, and fail-closed execution.
  - [x] Document setup and validation in `docs/phase3-validation.md`; provide the checksum-verifying portable Blender installer in `scripts/install_blender.py`.
  - Isolation uses Linux Bubblewrap namespaces and per-process limits. Aggregate cgroup quotas and protection against hostile concurrent local writers remain future hardening, not completed guarantees.

---

## Leo revision point before Phase 4

Revision checkpoint: fixes from Leo's foundation review, recorded before starting agent orchestration. This records the implemented revision; it does not claim manual Inspector validation or all future hardening is complete.

- [x] Log review findings before remediation in `todo.md`.
- [x] Reject hard-linked files and use descriptor-relative, no-symlink general file access with atomic writes (`workspace_io.py` [CRITICAL INTEGRITY]).
- [x] Fix isolated pytest imports for workspace-root and `src/` modules.
- [x] Preserve empty/nested directories in execution snapshots.
- [x] Add nine regression tests; the updated 48-test suite passes, with final Phase 3 checks and lint also passing.
- [x] Document Blender capabilities, execution/export limits, and remaining boundaries in `docs/blender-mcp-limitations.md`.
- [x] Keep remaining integration, concurrency, budget enforcement, resource quota, and authorization work explicitly pending in `todo.md`.
- [ ] Validate the real client/stdio connection during Phase 4.1; retain the pending Inspector checks from Phase 2.

---

### MCP contract revision before Phase 4

- [x] Add `contracts.py` [INTEGRITY] for constrained inputs and typed usage/QA/Blender result schemas.
- [x] Add `tool_errors.py` [CRITICAL INTEGRITY] to preserve expected error messages while leaving unexpected crashes generic.
- [x] Verify all 13 tools publish valid input/output schemas and supply structured results; retain compatibility text content.
- [x] Publish strict token, string, script, and decimal-cost constraints; enforce the configured encoded file-write limit before mutation.
- [x] Verify the saved over-budget warning and successful/error results through initialized in-memory MCP client/server sessions.
- [x] Document contracts in `docs/mcp-tool-contracts.md`; add ten contract tests, bringing the full suite to 58 tests.
- [ ] Validate production stdio/desktop/Inspector during Phase 4.1; retain pending budget retry/idempotency work.

## Phase 4: Provider-Neutral Agent Orchestration (The Client Layer)
*Goal: Connect the MCP toolbox to role-based agents using compatible hosted or local models, without coupling roles or the server to one provider.*

- [ ] **1. Connect Any Compatible MCP Host (Manual Game Director Mode)**
  - [x] Add `client.py` [HIGH PRIVILEGE] with provider-independent stdio launch settings, MCP initialization, discovery, ping, and optional resource diagnostics. No LLM calls or provider keys required.
  - [x] Add trusted `config/mcp-server.example.json` [INTEGRITY] and native Linux/Windows-to-WSL host configuration examples in `docs/phase4-provider-neutral.md`.
  - [x] Verify the real server over stdio with temporary workspace/ledger settings: all tools/resources, live hardware/budget JSON, memory, and clean restarts.
  - [ ] Connect the user's chosen MCP host and compatible model; Claude Desktop is an optional example, not a requirement. Verify architecture-memory access and a supervised game-file task.
  - [ ] Complete pending manual Inspector checks. Automated stdio tests do not replace desktop/UI validation.
- [x] **2. Define Provider-Neutral Agent Roles and Enforce Permissions**
  - [x] Create trusted `roles/` [INTEGRITY] profiles (`writer.yaml`, `programmer.yaml`, `artist.yaml`, `qa.yaml`) [INTEGRITY] [CONDITIONAL PRIVACY]: prompts, allowed tools/resources, and step limits.
  - [x] Keep role permissions separate from model/provider assignments and credentials.
  - [x] Implement trusted dispatcher authorization for every tool/resource call; reject forged/disallowed calls even when not advertised to the model.
  - [x] Keep usage logging and process launch configuration under trusted orchestrator control rather than model-selected arguments.
  - [x] Bind roles at server launch with `--role`; expose only allowed capabilities and enforce per-process tool/resource call limits even for raw MCP clients.
  - [x] Load immutable safe-YAML profiles within code-level permission ceilings; reject linked profiles, unknown settings, role injection, and accounting access.
  - [x] Add nine loader/dispatcher tests and two real-stdio tests; document trusted/operator versus role-scoped connections in `docs/phase4-roles.md`.
  - `max_steps` and role-prompt forwarding are enforced by the Phase 4.3 loop; tool/resource limits also remain enforced at the dispatcher/server boundaries.
- [x] **3. Build Provider Adapters and the Custom Orchestrator Loop**
  - [x] Define a model adapter interface for messages, schemas, tool calls/results, capabilities, and usage; reject unsupported models explicitly.
  - [x] Add configurable hosted/local provider adapters as needed, with endpoint/model/credential settings outside roles and outside agent-writable files. No single vendor/model is mandatory.
  - [x] Add bounded task loops, error handling, review/revision decisions, and audit records without secrets.
  - [x] Check/reserve budget before each model call; settle actual usage with idempotent logging and recovery for uncertain outcomes.
  - [x] Use the same MCP tools and role policies when switching model adapters; test adapters with fake responses before live provider calls.
  - [x] Add `accounting.py` [CRITICAL INTEGRITY] [PRIVACY] for serialized reservations, idempotent settlement, durable task/tool identities, audit metadata, and explicit reconciliation. Preserve legacy ledger records.
  - [x] Add an offline ping-only demo and task-status CLI in `orchestrator.py` [CRITICAL PRIVILEGE]; real final answers default to `needs_review`, with injectable review/revision decisions.
  - [x] Test both provider protocols with mocked HTTP and real scoped MCP processes, including cancellation and unknown side effects. Document operations/recovery in `docs/phase4-orchestrator.md`.
- [ ] **4. Phase 4 Milestone Validation**
  - [x] Test role permissions, forged calls, resource policy, step limits, provider capability errors, budget reservations, idempotent settlement, and conservative crash/restart handling with temporary state.
  - [x] Complete an offline CLI demo and end-to-end mock-provider tasks over real role-scoped stdio; verify the same roles/tools work with both implemented protocol adapters.
  - [ ] Complete a supervised end-to-end task with the selected host/model and record provider-specific limitations. Validate another configured model/adapter before claiming interchangeable provider support.

Model independence means compatible hosts/adapters can reuse the toolbox. It does not mean every raw LLM API or every model supports MCP/tool calling automatically.
