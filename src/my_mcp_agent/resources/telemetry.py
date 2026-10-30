from mcp.server.mcpserver import MCPServer
from my_mcp_agent.config import DAILY_BUDGET_USD


def register_telemetry_resources(mcp: MCPServer) -> None:
    @mcp.resource("studio://telemetry/status")
    def get_studio_status() -> str:
        """Basic health check resource for Phase 0."""
        return f"Telemetry online. Daily budget cap: ${DAILY_BUDGET_USD:.2f}"