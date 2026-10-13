"""Tiny MCP stdio server used by the integration tests."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fake")


@mcp.tool()
def add(a: int, b: int) -> str:
    """Add two integers."""
    return str(a + b)


if __name__ == "__main__":
    mcp.run()
