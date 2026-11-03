"""Usage accounting tool; model-call authorization belongs to the orchestrator."""

from mcp.server.mcpserver import MCPServer

from my_mcp_agent.contracts import CostUSD, Identity, TokenCount, UsageLogResult
from my_mcp_agent.ledger import record_task_usage
from my_mcp_agent.tool_errors import agent_tool


def log_task_usage(
    agent_role: Identity,
    model: Identity,
    input_tokens: TokenCount,
    output_tokens: TokenCount,
    cost_usd: CostUSD,
) -> UsageLogResult:
    """Record incurred usage and return UTC daily totals with decimal USD strings.

    Supply actual USD cost as a decimal string, e.g. "0.0125". An over-budget
    call records the usage then raises an error; do not retry it. This is not
    a model execution gate or an automatically calculated pricing estimate.
    """
    return record_task_usage(agent_role, model, input_tokens, output_tokens, cost_usd)


def register_budget_tools(mcp: MCPServer) -> None:
    mcp.tool()(agent_tool(log_task_usage))
