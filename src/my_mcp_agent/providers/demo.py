"""Deterministic local demo: no HTTP, API key, payment, or game-file mutation."""

from my_mcp_agent.providers.base import (
    Message,
    ModelReply,
    PreparedRequest,
    ProviderConfig,
    ToolCall,
    Usage,
)


class DemoAdapter:
    config = ProviderConfig(
        protocol="demo",
        model="offline-demo",
        supports_tools=True,
        input_usd_per_million="0",
        output_usd_per_million="0",
        reservation_usd="0",
    )

    def prepare(self, messages: list[Message], tools: list[dict]) -> PreparedRequest:
        return PreparedRequest(
            payload={"turn": sum(message.role == "assistant" for message in messages)}
        )

    async def send(self, request: PreparedRequest) -> ModelReply:
        if request.payload["turn"] == 0:
            return ModelReply(
                calls=(ToolCall(id="demo_ping", name="workspace_ping", arguments={}),),
                usage=Usage(input_tokens=0, output_tokens=0),
            )
        return ModelReply(
            text="Offline demo completed: role-scoped MCP ping succeeded; no game files were changed.",
            usage=Usage(input_tokens=0, output_tokens=0),
        )
