"""Fail-closed Linux execution using Bubblewrap and disposable workspace copies."""

import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from my_mcp_agent import config
from my_mcp_agent.security import SandboxViolationError, validate_path


def snapshot_workspace(destination: Path) -> None:
    """Copy readable regular files, never links, devices, credentials or Git data."""
    total = count = 0
    root = config.ALLOWED_WORKSPACE
    for directory, dirs, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        safe_dirs = []
        for name in dirs:
            try:
                validate_path(str(parent / name))
            except SandboxViolationError:
                continue
            count += 1
            if count > config.SNAPSHOT_MAX_FILES:
                raise ValueError("Workspace exceeds execution snapshot entry limits.")
            (destination / (parent / name).relative_to(root)).mkdir(
                parents=True, exist_ok=True
            )
            safe_dirs.append(name)
        dirs[:] = safe_dirs
        for name in files:
            source = parent / name
            try:
                source = validate_path(str(source))
            except SandboxViolationError:
                continue
            # Walk by directory descriptors: no ancestor symlink can redirect
            # this copy after validation. Reject hard links to outside data too.
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                relative = source.relative_to(root)
                for component in relative.parts[:-1]:
                    next_fd = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=directory_fd,
                    )
                    os.close(directory_fd)
                    directory_fd = next_fd
                fd = os.open(
                    relative.name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=directory_fd,
                )
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        continue
                    data = stream.read(config.SNAPSHOT_MAX_BYTES - total + 1)
            finally:
                os.close(directory_fd)
            total += len(data)
            count += 1
            if total > config.SNAPSHOT_MAX_BYTES or count > config.SNAPSHOT_MAX_FILES:
                raise ValueError("Workspace exceeds execution snapshot limits.")
            target = destination / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def run_isolated(
    command: list[str],
    workspace: Path,
    output: Path,
    extra_mounts: tuple[tuple[Path, str], ...] = (),
) -> dict:
    """Run without host home, credentials, network, or writable host workspace.

    Requires user namespaces. Runtime/system files are read-only. CPU, address
    space, file-size and wall-time limits apply. Output is capped on return.
    This is namespace isolation, not a VM or a defense against kernel exploits.
    """
    bwrap = shutil.which("bwrap")
    prlimit = shutil.which("prlimit")
    if sys.platform != "linux" or not bwrap or not prlimit:
        raise RuntimeError(
            "Linux, Bubblewrap and prlimit are required; execution refused."
        )
    args = [
        prlimit,
        "--as=4294967296",
        "--cpu=30",
        "--nproc=256",
        "--fsize=52428800",
        "--",
        bwrap,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
    ]
    for name in ("/usr", "/bin", "/lib", "/lib64"):
        if Path(name).exists():
            args += ["--ro-bind", name, name]
    args += [
        "--ro-bind",
        str(Path(sys.prefix).resolve()),
        "/runtime",
        "--ro-bind",
        str(workspace),
        "/workspace",
        "--bind",
        str(output),
        "/output",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/home/sandbox",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--clearenv",
        "--setenv",
        "HOME",
        "/home/sandbox",
        "--setenv",
        "PATH",
        "/runtime/bin:/usr/bin:/bin",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--setenv",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "1",
        "--setenv",
        "OMP_NUM_THREADS",
        "1",
        "--setenv",
        "OPENBLAS_NUM_THREADS",
        "1",
    ]
    for source, target in extra_mounts:
        args += ["--ro-bind", str(source), target]
    args += ["--chdir", "/workspace", "--", *command]
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            args,
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env={"PATH": "/usr/bin:/bin"},
        )
        timed_out = False
        try:
            process.wait(timeout=config.EXECUTION_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # Kill descendants even if the direct process exited first.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        stdout.seek(0)
        stderr.seek(0)
        out = stdout.read(config.EXECUTION_OUTPUT_BYTES + 1)
        err = stderr.read(config.EXECUTION_OUTPUT_BYTES + 1)
    if process.returncode and b"bwrap:" in err:
        raise RuntimeError(
            "Bubblewrap isolation failed; command was not run without isolation."
        )
    return {
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "stdout": out[: config.EXECUTION_OUTPUT_BYTES].decode(
            "utf-8", errors="replace"
        ),
        "stderr": err[: config.EXECUTION_OUTPUT_BYTES].decode(
            "utf-8", errors="replace"
        ),
        "output_truncated": len(out) > config.EXECUTION_OUTPUT_BYTES
        or len(err) > config.EXECUTION_OUTPUT_BYTES,
    }
