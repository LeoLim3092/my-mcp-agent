from mcp.server.mcpserver import MCPServer

# Initialize the MCP server using v2 syntax
mcp = MCPServer("HelloWorldServer")

@mcp.tool()
def say_hello(name: str) -> str:
    """Say hello to someone!"""
    return f"Hello, {name}! Welcome to the Model Context Protocol v2."

if __name__ == "__main__":
    mcp.run()