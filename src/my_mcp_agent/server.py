"""Studio MCP server; unscoped operator mode or a role-scoped stdio process."""

import argparse
from collections.abc import Sequence

from mcp.server.mcpserver import MCPServer

from my_mcp_agent.authorization import RoleRegistrar
from my_mcp_agent.config import ALLOWED_WORKSPACE, PROJECT_ROOT
from my_mcp_agent.resources.memory import register_memory_resources
from my_mcp_agent.resources.telemetry import register_telemetry_resources
from my_mcp_agent.roles import RoleName, RoleProfile, load_role
from my_mcp_agent.tools.budget import register_budget_tools
from my_mcp_agent.tools.external import register_external_tools
from my_mcp_agent.tools.filesystem import register_filesystem_tools
from my_mcp_agent.tools.git_ops import register_git_tools
from my_mcp_agent.tools.qa_runner import register_qa_tools


def initialize_workspace() -> None:
    """Create the game workspace only when starting the server."""
    if ALLOWED_WORKSPACE.is_relative_to(PROJECT_ROOT) or PROJECT_ROOT.is_relative_to(
        ALLOWED_WORKSPACE
    ):
        raise RuntimeError("The game workspace and MCP project must be separate trees.")
    ALLOWED_WORKSPACE.mkdir(parents=True, exist_ok=True)


def create_server(profile: RoleProfile | None = None) -> MCPServer:
    """Build an operator server or a dedicated immutable role-scoped server."""
    initialize_workspace()
    server = MCPServer(
        "SoloGameStudio" if profile is None else f"SoloGameStudio-{profile.name}"
    )
    registrar = server if profile is None else RoleRegistrar(server, profile)
    for register in (
        register_filesystem_tools,
        register_git_tools,
        register_qa_tools,
        register_external_tools,
        register_budget_tools,
        register_telemetry_resources,
        register_memory_resources,
    ):
        register(registrar)
    return server


# Existing MCP Inspector/module launchers retain the full operator toolbox.
# Agents should use `python -m my_mcp_agent.server --role NAME` instead.
mcp = create_server()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Launch operator or role-scoped studio MCP."
    )
    parser.add_argument(
        "--role",
        choices=[role.value for role in RoleName],
        help="Bind this process to a trusted agent role. Omit only for operator diagnostics.",
    )
    arguments = parser.parse_args(argv)
    server = create_server(load_role(arguments.role)) if arguments.role else mcp
    server.run()


if __name__ == "__main__":
    main()
