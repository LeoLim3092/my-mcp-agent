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
  - [✓] `write_file(rel_path: str, content: str)`: Creates missing parent folders and writes content to disk.
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
  - [x] `run_tests(test_target: str)`: Runs isolated `pytest` on a workspace snapshot and returns exit code, pass/fail, bounded stdout/stderr, and timeout status.
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

## Phase 4: Multi-Agent Studio Orchestration (The Client Layer)
*Goal: Connect the MCP server toolbox to role-based AI personas.*

- [ ] **1. Connect to Claude Desktop (Manual Game Director Mode)**
  - [ ] Add WSL `uv run` command to Windows `claude_desktop_config.json` [INTEGRITY] [CONDITIONAL PRIVACY]:
    `wsl.exe uv --directory /home/leolim/repo/my-mcp-agent run mcp run src/my_mcp_agent/server.py`
  - [ ] Test directing Claude to read `studio://memory/architecture` and scaffold a game feature.
- [ ] **2. Define Agent Role Profiles (`roles/` [INTEGRITY] directory)**
  - [ ] **Game Writer (`writer.yaml` [INTEGRITY] [CONDITIONAL PRIVACY]):** Prompt + allowed tools (`read_file`, `write_file`, `fetch_web_docs`).
  - [ ] **Lead Programmer (`programmer.yaml` [INTEGRITY] [CONDITIONAL PRIVACY]):** Prompt + allowed tools (`read_file`, `write_file`, `patch_file`, `run_linter`, `run_tests`, `git_checkpoint`).
  - [ ] **3D Technical Artist (`artist.yaml` [INTEGRITY] [CONDITIONAL PRIVACY]):** Prompt + allowed tools (`read_file`, `run_blender_script`).
  - [ ] **QA Tester (`qa.yaml` [INTEGRITY] [CONDITIONAL PRIVACY]):** Prompt + allowed tools (`read_file`, `git_diff`, `run_linter`, `run_tests`).
- [ ] **3. Build the Custom Python Orchestrator Loop**
  - [ ] Write an MCP client script [CRITICAL INTEGRITY] [CRITICAL PRIVILEGE] that loads a role profile, checks `studio://telemetry/budget` pre-flight, executes the task via LLM + MCP tools, and records cost via `log_task_usage`.