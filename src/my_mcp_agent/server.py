from mcp.server.mcpserver import MCPServer

from my_mcp_agent.config import ALLOWED_WORKSPACE, PROJECT_ROOT

from my_mcp_agent.tools.filesystem import register_filesystem_tools
from my_mcp_agent.tools.git_ops import register_git_tools
from my_mcp_agent.tools.qa_runner import register_qa_tools
from my_mcp_agent.tools.external import register_external_tools
from my_mcp_agent.tools.budget import register_budget_tools
from my_mcp_agent.resources.telemetry import register_telemetry_resources
from my_mcp_agent.resources.memory import register_memory_resources

def initialize_workspace() -> None:
    """Create the game workspace only when starting the server."""
    if ALLOWED_WORKSPACE.is_relative_to(PROJECT_ROOT) or PROJECT_ROOT.is_relative_to(
        ALLOWED_WORKSPACE
    ):
        raise RuntimeError("The game workspace and MCP project must be separate trees.")
    ALLOWED_WORKSPACE.mkdir(parents=True, exist_ok=True)


# Module-based MCP launchers also load this entry point during startup.
initialize_workspace()

# Initialize the MCP v2.x server
mcp = MCPServer("SoloGameStudio")

# Register all capability modules
register_filesystem_tools(mcp)
register_git_tools(mcp)
register_qa_tools(mcp)
register_external_tools(mcp)
register_budget_tools(mcp)

register_telemetry_resources(mcp)
register_memory_resources(mcp)

if __name__ == "__main__":
    mcp.run()
