# Blender MCP capabilities and limitations

This document describes the current `run_blender_script` implementation. Limits
are operator-controlled settings, not arguments an agent can override.

## How it works

1. A connected agent writes a Blender Python (`bpy`) script and calls
   `run_blender_script(script_content, blend_file=None)`.
2. The server copies readable, policy-approved game files into a temporary snapshot.
3. Headless Blender runs in Bubblewrap isolation. Inputs are available under
   `/workspace`; generated files must be written under `/output`.
4. When Blender exits successfully, the server validates the export set and
   publishes supported files to `~/game_workspace/assets/generated/`.
5. The agent receives `exit_code`, `timed_out`, `stdout`, `stderr`,
   `output_truncated`, and exported workspace-relative paths in `exports`.

The MCP server provides execution tools. A connected client supplies the agent
that plans scripts and interprets results; the custom Phase 4 orchestrator is not
implemented yet. Each call starts a fresh Blender process. To continue editing a
previous model, supply its exported workspace `.blend` path as `blend_file`.

## Current limits

| Area | Current behavior | Consequence |
| --- | --- | --- |
| Platform | Linux/WSL, Bubblewrap, `prlimit`, and working user namespaces required | Execution is refused if isolation is unavailable; no unrestricted fallback |
| Blender runtime | Operator-configured executable; local portable runtime or `PATH` | Agent cannot choose another executable; API/add-on availability depends on the installed Blender |
| Interface | Headless Python execution; factory startup and file autoexecution disabled | No interactive GUI session; an agent must express modeling operations in code |
| Script size | Nonempty UTF-8 script, at most 1,000,000 bytes | Split large workflows into separate calls and save intermediate models |
| Wall time | 30 seconds for the launched command | Slow modeling, baking, simulation, or rendering may time out; snapshot preparation and export publication are outside this timer |
| CPU | 30 CPU seconds per process; Blender launched with one thread | Computationally heavy work is constrained; this is not an aggregate job CPU quota |
| Memory | 4 GiB address space per process | Large scenes can fail; this is not a total RAM quota across all child processes |
| Processes | `RLIMIT_NPROC` set to 256 | User/process accounting can affect availability; this is not a dedicated job cgroup PID quota |
| File size | 52,428,800 bytes (50 MiB) per written file | Large `.blend`, texture, or export files may fail even below the combined export limit |
| Input snapshot | At most 100,000,000 bytes and 5,000 admitted directory/file entries | The whole readable workspace snapshot must fit, even when the script needs only one model |
| Export set | At most 100,000,000 bytes and 5,000 regular files | Large batches must be reduced; per-file limits also apply |
| Text output | First 100,000 bytes of stdout and stderr returned separately | Logs may be truncated; use concise summaries |
| Network | Unavailable inside execution | Scripts cannot download assets, packages, textures, or remote services |
| Host access | Host home, server source, and ledger are not mounted; environment is cleared | Scripts cannot use host credentials or ordinary files outside the admitted snapshot/runtime mounts |
| Workspace inputs | Read-only snapshot; protected paths, symlinks, hard links, and special files excluded | Script changes to input paths do not persist; linked or excluded dependencies may be missing |
| GPU | GPU devices are not explicitly passed through | GPU-dependent rendering or compute is not supported by the current setup |

Values come from `config.py`, `execution.py`, and `tools/external.py`. CPU, memory,
process, and file-size restrictions are implemented with `prlimit`; some values
are currently fixed in the runner rather than configurable constants.

## Saving and exporting

Allowed output extensions:

```text
.blend  .fbx  .glb  .gltf  .bin  .png  .jpg  .jpeg
```

All exported files must be regular files under `/output`. Output symlinks,
unsupported extensions, protected destination names, and oversized export sets
are refused. An unsupported auxiliary file, such as a `.blend1` backup or `.mtl`,
can cause the entire pre-publication validation to fail. Configure scripts to
produce only supported outputs.

A successful Blender exit alone does not guarantee publication: export validation
or filesystem errors can still fail the tool call. Failed/timed-out Blender runs
publish nothing. Files left only in `/tmp` disappear when the call finishes.

For example:

```python
bpy.ops.wm.save_as_mainfile(filepath="/output/pine_tree.blend")
bpy.ops.export_scene.gltf(filepath="/output/pine_tree.glb", export_format="GLB")
```

These become:

```text
~/game_workspace/assets/generated/pine_tree.blend
~/game_workspace/assets/generated/pine_tree.glb
```

Existing destination files are replaced. There is no automatic versioning or
conflict detection. Each file is published individually, so a failure partway
through publication can leave a partially updated multi-file asset. Concurrent
agents must not publish to the same filenames without coordination.

Export validation checks paths, types, extensions, and sizes. It does not inspect
asset contents for correct topology, safe embedded data, valid external references,
engine compatibility, or visual quality. The script is responsible for keeping
`.gltf` buffers and textures together and using suitable relative references;
`.glb` often simplifies single-file delivery.

## Modeling ability and quality

Procedural low-poly props are a practical use case: trees, rocks, crates, simple
buildings, and repeated scene elements can be created from geometry and materials.
An agent can print triangle counts, dimensions, object names, and other checks,
then revise its script based on the result.

The tool does not guarantee artistic quality, a triangle budget, correct scale,
UVs, clean topology, pivots, collisions, LODs, rigging, animation, or engine import
settings. Those requirements must be stated, implemented, and validated explicitly.
Materials and appearance can also change when exported or imported into a game engine.

There is no automatic render-and-preview loop. Scripts may render supported image
files within the limits, but this tool returns filenames and text rather than
showing the image to the agent. Visual inspection requires another image-capable
client/tool or manual review in Blender/the target engine.

## Example: low-poly tree request

> Create a stylized pine tree, 3 metres tall, under 500 triangles, with a
> bottom-centred origin and simple trunk/foliage materials. Export
> `pine_tree.blend` and `pine_tree.glb`. Print the triangle count, dimensions,
> material names, and any validation failures.

This is within the intended scope, subject to execution limits and successful
validation. Triangle counts should be checked after relevant modifiers or
triangulation; Blender polygon count is not automatically the same as triangle count.

## Remaining security and workflow boundaries

Bubblewrap namespaces share the host kernel. They do not provide VM isolation,
aggregate cgroup RAM/disk quotas, or protection against every hostile local actor.
Filename filtering does not identify secrets embedded in otherwise allowed game
files. Treat generated `.blend` files and other asset contents as untrusted.

Further work includes aggregate resource quotas, concurrent export coordination,
stronger protection against malicious local directory relocation, a visual preview
workflow, and automated game-engine import validation. See [todo.md](../todo.md)
and [Phase 3 validation](phase3-validation.md) for the broader task list and setup.
