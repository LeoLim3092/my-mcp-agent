"""Descriptor-relative workspace access for Linux/WSL file tools.

No component is followed as a symlink. Hard-linked files are refused; writes
replace directory entries atomically rather than truncating existing inodes.
These operations do not provide conflict detection between concurrent writers.
"""

import os
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path

from my_mcp_agent import security
from my_mcp_agent.security import SandboxViolationError


def _parts(path: str | Path, operation: str) -> tuple[str, ...]:
    resolved = security.validate_path(str(path), operation=operation)
    # Reapply name policy if resolution observed a concurrent path replacement.
    security.validate_path(str(resolved), operation=operation)
    return resolved.relative_to(security.ALLOWED_WORKSPACE).parts


@contextmanager
def _directory(parts: tuple[str, ...], create: bool = False):
    fd = os.open(
        security.ALLOWED_WORKSPACE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            try:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                )
            except OSError as error:
                if isinstance(error, FileNotFoundError):
                    raise
                raise SandboxViolationError(
                    "Cannot safely open workspace directory."
                ) from error
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _regular(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Expected a regular file.")
    if info.st_nlink != 1:
        raise SandboxViolationError("Hard-linked files are forbidden.")


def read_bytes(path: str | Path, limit: int) -> bytes:
    parts = _parts(path, "read")
    if not parts:
        raise ValueError("Expected a regular file.")
    with _directory(parts[:-1]) as parent:
        try:
            fd = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
            )
        except OSError as error:
            if isinstance(error, FileNotFoundError):
                raise
            raise SandboxViolationError("Cannot safely open workspace file.") from error
        try:
            _regular(os.fstat(fd))
        except BaseException:
            os.close(fd)
            raise
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"File exceeds the {limit}-byte read limit.")
        return data


def _destination(parent: int, name: str):
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        raise SandboxViolationError("Symlink destinations are forbidden.")
    _regular(info)
    return info


def write_bytes(path: str | Path, data: bytes) -> None:
    parts = _parts(path, "write")
    with _directory(parts[:-1], create=True) as parent:
        existing = _destination(parent, parts[-1])
        temporary = ".studio-write-" + secrets.token_hex(16)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode=0o600,
            dir_fd=parent,
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                if existing is not None:
                    os.fchmod(stream.fileno(), stat.S_IMODE(existing.st_mode) & 0o777)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            _destination(parent, parts[-1])
            os.replace(temporary, parts[-1], src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def list_entries(path: str) -> list[str]:
    parts = _parts(path, "read")
    entries = []
    try:
        with _directory(parts) as directory:
            for name in sorted(os.listdir(directory)):
                target = security.ALLOWED_WORKSPACE.joinpath(*parts, name)
                try:
                    security.validate_path(str(target))
                    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                except SandboxViolationError, FileNotFoundError:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    entries.append(name + "/")
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    entries.append(name)
    except FileNotFoundError as error:
        raise NotADirectoryError("Expected an existing workspace directory.") from error
    return entries
