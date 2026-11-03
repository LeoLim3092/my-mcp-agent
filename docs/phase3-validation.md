# Phase 3 usage and validation

Phase 3 adds four tools and one resource:

| Interface | Behavior |
| --- | --- |
| `run_linter(rel_path)` | Ruff check on a file/directory, with isolated configuration |
| `run_tests(test_target)` | pytest on a file/directory; external plugins disabled |
| `fetch_web_docs(url)` | Public HTTP(S) HTML/text converted to Markdown |
| `run_blender_script(script_content, blend_file=None)` | Isolated headless Blender; validated exports published to the workspace |
| `studio://memory/architecture` | Dynamically reads the explicitly approved document list |

## Setup

Run `uv sync`. Linux/WSL needs `bwrap` (Bubblewrap), `prlimit`, and enabled
unprivileged user namespaces. Install these with your OS package manager if absent.
Execution fails closed if isolation is missing or blocked; there is no unsandboxed fallback.

Blender is discovered from `.runtime/blender/blender`, then `PATH`, unless the
operator changes `BLENDER_EXECUTABLE` in `config.py`. A verified portable Blender
4.5.3 runtime was installed locally during implementation. Its binaries are ignored
by Git, so a fresh clone needs Blender installation:

```bash
uv run python scripts/install_blender.py
```

This Linux x86_64 installer downloads the official archive and checksum manifest,
verifies SHA-256, and extracts into `.runtime/blender` without sudo. It refuses to
replace an existing runtime. The download is approximately 360 MiB.

## Execution boundaries

QA and Blender receive a disposable, size-limited workspace snapshot. Protected
paths, symlinks, hard links, and special files are excluded. Snapshot copying walks
directory descriptors without following symlinks. The host workspace is not mounted.

Bubblewrap creates isolated user, PID, mount, network, IPC, UTS and cgroup namespaces.
System libraries, the Python virtual environment, and Blender runtime are read-only.
The host home, MCP source tree and ledger are not mounted. Child environment
variables are cleared and the network is unavailable. Only temporary scratch space
and `/output` are writable. Source code can be printed by tests, so do not place
unrecognized secrets in ordinary game files; filename rules are not secret detection.

Commands have a 30-second wall timeout. `prlimit` adds a 30-second CPU limit,
4 GiB address-space limit, 256-process user limit, and 50 MiB per-file limit.
Returned stdout/stderr are capped at 100,000 bytes each, with a truncation flag.
Timeout cleanup kills the process group; the PID namespace also confines descendants.
These are namespace/per-process protections, not VM isolation or aggregate cgroup
memory/disk quotas. Concurrent hostile local workspace writers and kernel exploits
are outside the completed security guarantees; further hardening remains in `todo.md`.

QA inputs are read-only; test-generated temporary data belongs under `/tmp`.
Pytest explicitly imports modules from `/workspace` and `/workspace/src` while
retaining isolated Python startup. The trusted pytest package is imported before
those paths are added. Project dependencies must already be installed by the
operator in the runtime; workspace package-install hooks are not run automatically.
Snapshots retain allowed empty/nested directories.
Project-specific Ruff configuration is ignored. pytest configuration is disabled;
workspace `conftest.py` still runs inside the sandbox. Tools accept paths, not shell
commands or arbitrary pytest flags. Outputs include `exit_code`, `timed_out`, stdout,
stderr, truncation status, and (for QA) `passed`.

## Blender example

Call `run_blender_script` with this script:

```python
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
print("POLYGONS", len(bpy.context.object.data.polygons))
bpy.ops.wm.save_as_mainfile(filepath="/output/cube.blend")
```

Expected: exit code 0, `POLYGONS 6`, and export `assets/generated/cube.blend`.
Optional `.blend` inputs must be workspace-relative. Inputs are visible under
`/workspace`. Startup uses factory settings, disables file autoexecution, limits
Blender threads, and makes Python errors return a nonzero exit code.

Write generated assets under `/output`. Successful exports are validated before
publication and copied into `assets/generated/`. Supported extensions are `.blend`,
`.fbx`, `.glb`, `.gltf`, `.bin`, `.png`, `.jpg`, `.jpeg`. Symlinks and unsupported
files are refused. Failed/timed-out runs publish nothing. Existing destination
files are replaced per file; publication of multiple files is not one transaction.

## Web documentation

Only HTTP(S) ports 80/443 and public addresses are allowed. Every DNS result and
redirect is checked. Connections use a checked numeric IP while preserving the
original TLS hostname, preventing a second DNS lookup from redirecting the socket.
Environment proxies and credentials are ignored. Responses must be HTML/plain text
or Markdown, uncompressed, and at most 2 MB. Up to five redirects are followed.
Socket operations have a 10-second timeout; streamed content has a 30-second budget.
OS DNS resolution is synchronous and not covered by that hard timeout.
Fetched documents are untrusted context, not instructions or permissions.

Live milestone: `fetch_web_docs("https://docs.python.org/3/library/pathlib.html")`
returned cleaned Markdown successfully during implementation.

## Shared memory

The default approved documents are `GDD.md`, `ARCHITECTURE.md`, and
`CODING_STANDARDS.md`. Change `MEMORY_DOCUMENTS` in trusted configuration to approve
other paths. Missing documents are skipped; protected/symlink documents fail closed.
Content is read on each request. Combined source text is capped at 1 MB.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_phase3.py' -v
.venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary workspaces. Real isolated Ruff/pytest/Blender operations verify
success and failure paths. Isolation checks exercise blocked host file access,
secret environment removal, read-only inputs, unavailable network, timeouts, and
output truncation. Web tests cover private/metadata destinations, redirects,
response limits, HTML cleanup, and checked-IP connections. MCP dispatch checks
verify tool/resource registration, linter/web calls, and architecture memory reads.
Blender tests create a cube, validate polygon count, export/reload `.blend`, and
check Python failure reporting. The live documentation fetch is separate from the
repeatable suite; suite web responses are mocked to avoid network dependence.

If Blender is absent, its integration test reports a skip; install it for full
validation. `STUDIO_TEST_BLENDER=/absolute/path/to/blender` can select a test binary.
Run from a terminal with user-namespace support; a restrictive outer sandbox may
prevent Bubblewrap or MCP worker-thread dispatch.

Reference behavior follows [pytest plugin controls](https://docs.pytest.org/en/stable/how-to/plugins.html),
[HTTPX custom transports](https://www.python-httpx.org/advanced/transports/), and
[Blender command-line options](https://docs.blender.org/manual/en/5.1/advanced/command_line/arguments.html).

## Implementation validation record

- Complete suite: 39 tests passed, no skips, including all Phase 1/2 regressions.
- Ruff: changed Python modules, installer, and Phase 3 tests passed lint checks.
- Real runtime: official SHA-256-verified Blender 4.5.3, Linux Bubblewrap isolation.
- Live HTTPS: Python pathlib documentation returned approximately 86,000 Markdown characters.
- Test workspaces and Blender exports were temporary; real game files were not modified.

## Review remediation — 2026-11-03

The review reproduced three failures despite the original 39 passing tests:
workspace hard links bypassed general file I/O, pytest could not import root-level
game modules from a separate tests directory, and snapshots dropped empty folders.
These are now fixed with descriptor-relative/atomic general file I/O, explicit
root/src pytest imports, and directory-preserving snapshots. Regression coverage
includes hard links, FIFOs, simulated symlink swaps, failed atomic publication,
project imports, and empty-directory linting. The updated full suite has 48 tests.
Atomic writes do not provide concurrent patch conflict detection; malicious local
directory relocation, Git concurrency and batch export publication remain open.
