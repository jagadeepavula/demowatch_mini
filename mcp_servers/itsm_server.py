"""MCP server #1: mock ServiceNow. Reads the itsm schema in Supabase."""
from mcp.server.fastmcp import FastMCP
from db import query

mcp = FastMCP("itsm")


@mcp.tool()
def get_incident(incident_id: str) -> dict:
    """Look up one IT incident by its ID (for example INC0428).
    Returns priority, service, status, summary and when it was opened."""
    rows = query("select * from itsm.incidents where incident_id = %s",
                 (incident_id.upper().strip(),))
    return rows[0] if rows else {"found": False, "message": f"No incident {incident_id}"}


@mcp.tool()
def list_incidents(service: str = "", status: str = "") -> list[dict]:
    """List incidents, newest first. Optionally filter by service
    (payments, checkout, search) and/or status (open, resolved).
    Leave a filter empty to skip it."""
    return query(
        "select * from itsm.incidents "
        "where (%s = '' or service = %s) and (%s = '' or status = %s) "
        "order by opened_at desc",
        (service.lower(), service.lower(), status.lower(), status.lower()))


if __name__ == "__main__":
    mcp.run()  # stdio: the agent starts this process and talks to it
