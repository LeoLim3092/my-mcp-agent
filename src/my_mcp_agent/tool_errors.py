"""Expose expected failures as MCP tool errors without exposing crash details."""

from collections.abc import Callable
from functools import wraps

import httpcore
import httpx
from mcp.server.mcpserver.exceptions import ToolError

from my_mcp_agent.ledger import BudgetExceededError


class ToolOperationError(RuntimeError):
    """An explicitly anticipated operation/setup failure safe to explain to callers."""


def agent_tool[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Preserve the function signature/schema and translate expected failures.

    Apply only when registering: direct Python callers retain domain exceptions.
    Unexpected programming errors still follow the SDK's generic-error path.
    """

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except (
            ValueError,
            OSError,
            BudgetExceededError,
            ToolOperationError,
            httpx.HTTPError,
            httpcore.NetworkError,
            httpcore.TimeoutException,
            httpcore.ProtocolError,
        ) as error:
            raise ToolError(str(error) or type(error).__name__) from error

    return wrapped
