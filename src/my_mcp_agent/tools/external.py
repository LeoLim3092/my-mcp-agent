"""Public documentation fetching and isolated headless Blender execution."""

import os
import shutil
import tempfile
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from my_mcp_agent import config
from my_mcp_agent.execution import run_isolated, snapshot_workspace
from my_mcp_agent.security import validate_path
from my_mcp_agent.tools.web_docs import fetch_web_docs


def run_blender_script(script_content: str, blend_file: str | None = None) -> dict:
    """Run Python in isolated Blender with a 30-second limit and no network.

    Inputs appear under /workspace (read-only); write exports to /output.
    Successful outputs are copied to assets/generated/ in the game workspace.
    Supported outputs: .blend, .fbx, .glb, .gltf, .bin, .png, .jpg, .jpeg.
    Failed/timed-out runs publish nothing. The Blender executable is configured
    by the operator in config.py, never supplied by the agent.
    """
    if not script_content.strip() or len(script_content.encode()) > 1_000_000:
        raise ValueError("Provide a nonempty Blender script of at most 1 MB.")
    executable = shutil.which(config.BLENDER_EXECUTABLE)
    if not executable:
        raise RuntimeError("Blender is not installed/configured; execution refused.")
    executable = Path(executable).resolve()
    if blend_file is not None:
        blend_path = validate_path(blend_file)
        if not blend_path.is_file() or blend_path.suffix.lower() != ".blend":
            raise ValueError("blend_file must be an existing workspace .blend file.")
    with tempfile.TemporaryDirectory(prefix="studio-blender-") as directory:
        base = Path(directory)
        workspace, output = base / "workspace", base / "output"
        workspace.mkdir()
        output.mkdir()
        snapshot_workspace(workspace)
        script = base / "script.py"
        script.write_text(script_content, encoding="utf-8")
        # Portable Blender includes libraries/scripts alongside its executable.
        mounts = ((executable.parent, "/blender"), (script, "/script.py"))
        command = [
            f"/blender/{executable.name}",
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--threads",
            "1",
        ]
        if blend_file is not None:
            command += [
                "/workspace/"
                + blend_path.relative_to(config.ALLOWED_WORKSPACE).as_posix()
            ]
        command += ["--python-exit-code", "1", "--python", "/script.py"]
        result = run_isolated(command, workspace, output, mounts)
        result["exports"] = []
        if result["exit_code"] != 0 or result["timed_out"]:
            return result
        # Inspect the complete output set before publishing any files. Never
        # follow script-created symlinks or publish code/configuration files.
        exports = []
        total = 0
        for item in output.rglob("*"):
            if item.is_symlink():
                raise ValueError("Blender outputs must not contain symlinks.")
            if item.is_dir():
                continue
            if not item.is_file() or item.suffix.lower() not in {
                ".blend",
                ".fbx",
                ".glb",
                ".gltf",
                ".bin",
                ".png",
                ".jpg",
                ".jpeg",
            }:
                raise ValueError("Unsupported Blender export type.")
            total += item.stat().st_size
            if (
                total > config.SNAPSHOT_MAX_BYTES
                or len(exports) >= config.SNAPSHOT_MAX_FILES
            ):
                raise ValueError("Blender exports exceed limits.")
            relative = Path("assets/generated") / item.relative_to(output)
            destination = validate_path(relative.as_posix(), operation="write")
            exports.append((item, destination, relative.as_posix()))
        for source, destination, relative in exports:
            destination.parent.mkdir(parents=True, exist_ok=True)
            validate_path(relative, operation="write")
            # Replace the directory entry instead of writing through an existing
            # hard link. Temporary outputs stay outside the agent workspace.
            temporary_name = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent, delete=False
                ) as stream:
                    temporary_name = stream.name
                    with source.open("rb") as source_stream:
                        shutil.copyfileobj(source_stream, stream)
                os.replace(temporary_name, destination)
            finally:
                if temporary_name is not None:
                    Path(temporary_name).unlink(missing_ok=True)
            result["exports"].append(relative)
        return result


def register_external_tools(mcp: MCPServer) -> None:
    for tool in (fetch_web_docs, run_blender_script):
        mcp.tool()(tool)
