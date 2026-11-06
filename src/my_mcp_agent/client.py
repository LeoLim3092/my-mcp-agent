"""Provider-neutral stdio connection and diagnostics; no model API calls."""

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from my_mcp_agent.config import EXECUTION_TIMEOUT_SECONDS, PROJECT_ROOT


class StdioConnection(BaseModel):
    """Trusted operator launch settings, independent of any LLM/model provider.

    Loading this configuration authorizes executing its command. Keep it outside
    the agent-writable game workspace; do not place credentials in command args.
    """

    model_config = ConfigDict(extra="forbid")
    command: Annotated[str, Field(strict=True, min_length=1, pattern=r"\S")] = (
        sys.executable
    )
    args: tuple[StrictStr, ...] = ("-m", "my_mcp_agent.server")
    cwd: Path = PROJECT_ROOT
    request_timeout_seconds: Annotated[float, Field(gt=0, le=120)] = (
        EXECUTION_TIMEOUT_SECONDS + 15
    )


def load_connection(path: Path) -> StdioConnection:
    """Load a small, trusted local JSON launch configuration."""
    with path.open("rb") as stream:
        data = stream.read(65_537)
    if len(data) > 65_536:
        raise ValueError("Connection configuration exceeds 64 KiB.")
    return StdioConnection.model_validate_json(data)


@asynccontextmanager
async def connect_stdio(connection: StdioConnection) -> AsyncIterator[ClientSession]:
    """Start a trusted server, negotiate MCP, and clean it up when disconnected.

    The SDK supplies its minimal default environment; no LLM API key or provider
    configuration is needed. This connector grants no role-based authorization.
    """
    parameters = StdioServerParameters(
        command=connection.command,
        args=list(connection.args),
        cwd=str(connection.cwd),
    )
    try:
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(
                read, write, read_timeout_seconds=connection.request_timeout_seconds
            ) as session,
        ):
            await session.initialize()
            yield session
    except ExceptionGroup as group:
        # AnyIO wraps body/startup failures during transport cleanup. Preserve a
        # single underlying exception for callers; retain genuine multi-errors.
        error = group
        while isinstance(error, ExceptionGroup) and len(error.exceptions) == 1:
            error = error.exceptions[0]
        if error is group:
            raise
        raise error from group


async def inspect_server(
    connection: StdioConnection, resource_uris: Sequence[str] = ()
) -> dict:
    """List the studio tools/resources, ping, and optionally read advertised URIs.

    Calls no model and performs no game-file writes. A budget-resource read can
    initialize the runtime ledger. Each request uses the configured read timeout.
    """
    async with connect_stdio(connection) as session:
        tools = (await session.list_tools()).tools
        resources = (await session.list_resources()).resources
        advertised = {str(resource.uri) for resource in resources}
        unknown = set(resource_uris) - advertised
        if unknown:
            raise ValueError(
                f"Requested resources are not advertised: {sorted(unknown)}"
            )
        ping = await session.call_tool("workspace_ping", {})
        if ping.is_error:
            raise RuntimeError("MCP workspace ping failed.")
        contents = {}
        for uri in resource_uris:
            result = await session.read_resource(uri)
            contents[uri] = [
                item.model_dump(mode="json", by_alias=True, exclude_none=True)
                for item in result.contents
            ]
        return {
            "transport": "stdio",
            "initialized": True,
            "tools": [tool.name for tool in tools],
            "resources": [
                {"uri": str(resource.uri), "mime_type": resource.mime_type}
                for resource in resources
            ],
            "workspace_ping": ping.structured_content,
            "resource_results": contents,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect the studio MCP server without selecting an LLM."
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Trusted JSON command/args/cwd launch configuration.",
    )
    parser.add_argument(
        "--resource",
        action="append",
        default=[],
        help="Advertised resource URI to read; repeat for multiple resources.",
    )
    arguments = parser.parse_args()
    connection = (
        load_connection(arguments.config) if arguments.config else StdioConnection()
    )
    report = asyncio.run(inspect_server(connection, arguments.resource))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
