"""Trusted, provider-neutral roles with code-enforced capability ceilings."""

import os
import stat
from enum import StrEnum
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from my_mcp_agent.config import PROJECT_ROOT

ROLE_DIRECTORY = PROJECT_ROOT / "roles"


class RoleName(StrEnum):
    WRITER = "writer"
    PROGRAMMER = "programmer"
    ARTIST = "artist"
    QA = "qa"


COMMON_TOOLS = frozenset({"workspace_ping", "list_directory", "read_file"})
TOOL_CEILINGS = {
    RoleName.WRITER: COMMON_TOOLS | {"write_file", "fetch_web_docs"},
    RoleName.PROGRAMMER: COMMON_TOOLS
    | {
        "write_file",
        "patch_file",
        "git_status",
        "git_diff",
        "git_checkpoint",
        "run_linter",
        "run_tests",
    },
    RoleName.ARTIST: COMMON_TOOLS | {"run_blender_script"},
    RoleName.QA: COMMON_TOOLS | {"git_status", "git_diff", "run_linter", "run_tests"},
}
COMMON_RESOURCES = frozenset(
    {"studio://memory/architecture", "studio://telemetry/status"}
)
RESOURCE_CEILINGS = {
    RoleName.WRITER: COMMON_RESOURCES,
    RoleName.PROGRAMMER: COMMON_RESOURCES | {"studio://telemetry/hardware"},
    RoleName.ARTIST: COMMON_RESOURCES | {"studio://telemetry/hardware"},
    RoleName.QA: COMMON_RESOURCES | {"studio://telemetry/hardware"},
}
Nonblank = Annotated[str, Field(strict=True, min_length=1, pattern=r"\S")]


class RoleProfile(BaseModel):
    """Immutable role policy; model/provider/credentials are deliberately absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: RoleName
    description: Annotated[Nonblank, Field(max_length=1000)]
    system_prompt: Annotated[Nonblank, Field(max_length=10_000)]
    allowed_tools: frozenset[Nonblank]
    allowed_resources: frozenset[Nonblank]
    max_steps: Annotated[int, Field(strict=True, ge=1, le=100)] = 20
    max_tool_calls: Annotated[int, Field(strict=True, ge=1, le=100)] = 20
    max_resource_reads: Annotated[int, Field(strict=True, ge=1, le=100)] = 10

    @model_validator(mode="after")
    def enforce_capability_ceiling(self):
        if not self.allowed_tools <= TOOL_CEILINGS[self.name]:
            raise ValueError(
                "Role requests tools beyond its trusted capability ceiling."
            )
        if not self.allowed_resources <= RESOURCE_CEILINGS[self.name]:
            raise ValueError(
                "Role requests resources beyond its trusted capability ceiling."
            )
        return self


def load_role(name: RoleName | str) -> RoleProfile:
    """Load a named role from the trusted project directory, never a caller path.

    Safe YAML only, no symlink/hard-link files, no unknown settings, max 64 KiB.
    Restart a scoped server to apply operator edits; running policies stay frozen.
    """
    role = RoleName(name)
    directory = os.open(ROLE_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(
            f"{role.value}.yaml",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Role profiles must be regular, single-link files.")
            with os.fdopen(fd, "rb") as stream:
                fd = None
                data = stream.read(65_537)
        finally:
            if fd is not None:
                os.close(fd)
    finally:
        os.close(directory)
    if len(data) > 65_536:
        raise ValueError("Role profile exceeds 64 KiB.")
    profile = RoleProfile.model_validate(yaml.safe_load(data))
    if profile.name != role:
        raise ValueError("Role profile name does not match the requested role.")
    return profile
