"""MCP server #2: mock Splunk. Reads the logs schema in Supabase."""
from mcp.server.fastmcp import FastMCP
from db import query

mcp = FastMCP("logs")


@mcp.tool()
def search_logs(service: str, level: str = "", limit: int = 20) -> list[dict]:
    """Search application logs for one service (payments, checkout, search).
    Optionally filter by level (ERROR, WARN, INFO). Newest first."""
    return query(
        "select ts, service, level, message from logs.entries "
        "where service = %s and (%s = '' or level = %s) "
        "order by ts desc limit %s",
        (service.lower(), level.upper(), level.upper(), max(1, min(limit, 100))))


if __name__ == "__main__":
    mcp.run()
