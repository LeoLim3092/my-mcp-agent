"""Role enforcement at both the model dispatcher and stdio server boundary."""

from functools import wraps
from threading import Lock

from mcp import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError

from my_mcp_agent.roles import RoleProfile


class RoleAccessDenied(PermissionError):
    """A model requested a capability outside its assigned role."""


class RoleCallLimitError(PermissionError):
    """The trusted per-task/per-process role call allowance is exhausted."""


class _CallAllowance:
    def __init__(self, profile: RoleProfile):
        self._lock = Lock()
        self._tools = profile.max_tool_calls
        self._resources = profile.max_resource_reads

    def consume(self, kind: str) -> None:
        with self._lock:
            remaining = self._tools if kind == "tool" else self._resources
            if remaining <= 0:
                raise RoleCallLimitError(
                    f"Role {kind} call limit reached; end this task."
                )
            if kind == "tool":
                self._tools -= 1
            else:
                self._resources -= 1


class RoleDispatcher:
    """Only this facade, never the raw session, belongs in a future model loop.

    The orchestrator selects the role before executing model data. Call arguments
    cannot select a role, connection, or accounting identity. Failed authorized
    calls consume allowance too. max_steps is for the future model-turn loop.
    """

    def __init__(self, session: ClientSession, profile: RoleProfile):
        self._session = session
        self._profile = RoleProfile.model_validate(profile.model_dump())
        self._allowance = _CallAllowance(self._profile)

    @property
    def profile(self) -> RoleProfile:
        return self._profile

    async def verify_server_scope(self) -> None:
        """Fail before a model call if connected to an unscoped/mismatched server."""
        tools = {tool.name for tool in (await self._session.list_tools()).tools}
        resources = {
            str(resource.uri)
            for resource in (await self._session.list_resources()).resources
        }
        if (
            tools != self._profile.allowed_tools
            or resources != self._profile.allowed_resources
        ):
            raise RoleAccessDenied(
                "Connected server capabilities do not match the assigned role."
            )

    async def list_tools(self):
        tools = (await self._session.list_tools()).tools
        return [tool for tool in tools if tool.name in self._profile.allowed_tools]

    async def list_resources(self):
        resources = (await self._session.list_resources()).resources
        return [
            resource
            for resource in resources
            if str(resource.uri) in self._profile.allowed_resources
        ]

    async def call_tool(self, name: str, arguments: dict):
        if name not in self._profile.allowed_tools:
            raise RoleAccessDenied(
                f"Role '{self._profile.name}' cannot call tool '{name}'."
            )
        self._allowance.consume("tool")
        return await self._session.call_tool(name, arguments)

    async def read_resource(self, uri: str):
        if uri not in self._profile.allowed_resources:
            raise RoleAccessDenied(
                f"Role '{self._profile.name}' cannot read resource '{uri}'."
            )
        self._allowance.consume("resource")
        return await self._session.read_resource(uri)


class RoleRegistrar:
    """Expose only the role's capabilities in a dedicated server process.

    Unregistered calls fail even if a client bypasses RoleDispatcher. Allowances
    are shared by all callbacks in this server instance. Restart/task assignment
    is a trusted operator action, not a model tool. Profiles are frozen at startup.
    """

    def __init__(self, server: MCPServer, profile: RoleProfile):
        self._server = server
        self._profile = RoleProfile.model_validate(profile.model_dump())
        self._allowance = _CallAllowance(self._profile)

    def tool(self, **options):
        def register(function):
            if function.__name__ not in self._profile.allowed_tools:
                return function

            @wraps(function)
            def guarded(*args, **kwargs):
                try:
                    self._allowance.consume("tool")
                except RoleCallLimitError as error:
                    raise ToolError(str(error)) from error
                return function(*args, **kwargs)

            self._server.tool(**options)(guarded)
            return function

        return register

    def resource(self, uri: str, **options):
        def register(function):
            if uri not in self._profile.allowed_resources:
                return function

            @wraps(function)
            def guarded(*args, **kwargs):
                try:
                    self._allowance.consume("resource")
                except RoleCallLimitError as error:
                    raise ResourceError(str(error)) from error
                return function(*args, **kwargs)

            self._server.resource(uri, **options)(guarded)
            return function

        return register
