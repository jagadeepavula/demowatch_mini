"""MCP server #1: mock ServiceNow. Reads the itsm schema in Supabase.

Dates are UTC. `opened_from` is inclusive and `opened_to` is exclusive, as either
YYYY-MM-DD or "YYYY-MM-DD HH:MM". To cover all of 28 September use 2026-09-28 to 2026-09-29.
"""
from mcp.server.fastmcp import FastMCP
from db import query

mcp = FastMCP("itsm")

# one shared filter, so list and count always agree
WHERE = (
    "where (%(service)s = '' or service = %(service)s) "
    "and (%(status)s = '' or status = %(status)s) "
    "and (%(priority)s = '' or priority = %(priority)s) "
    "and (%(f)s = '' or opened_at >= (nullif(%(f)s,'')::timestamp at time zone 'UTC')) "
    "and (%(t)s = '' or opened_at <  (nullif(%(t)s,'')::timestamp at time zone 'UTC'))"
)


def _args(service, status, priority, opened_from, opened_to):
    return {"service": service.lower().strip(), "status": status.lower().strip(),
            "priority": priority.upper().strip(), "f": opened_from.strip(), "t": opened_to.strip()}


@mcp.tool()
def get_incident(incident_id: str) -> dict:
    """Look up one IT incident by its ID (for example INC0428).
    Returns priority, service, status (open, in_progress, on_hold or resolved), summary, opened_at,
    resolved_at, assignment_group (the owning team) and root_cause (often empty: open incidents, duplicates and some closures have none).
    Also returns category, source, customer_impact_count, parent_incident_id (duplicate of or caused by another incident),
    reopened_count, closed_reason and change_id."""
    rows = query("select * from itsm.incidents where incident_id = %s", (incident_id.upper().strip(),))
    return rows[0] if rows else {"found": False, "message": f"No incident {incident_id}"}


@mcp.tool()
def list_incidents(service: str = "", status: str = "", priority: str = "",
                   opened_from: str = "", opened_to: str = "", limit: int = 50) -> list[dict]:
    """List incidents, newest first. All filters are optional; leave one empty to skip it.
    service: payments, checkout, search, auth, inventory, catalog, notifications, shipping, loyalty.
    status: open, in_progress, on_hold or resolved. priority: P1 (worst) to P4.
    opened_from / opened_to: UTC dates, from inclusive and to exclusive."""
    sql = f"select * from itsm.incidents {WHERE} order by opened_at desc limit %(limit)s"
    return query(sql, {**_args(service, status, priority, opened_from, opened_to), "limit": max(1, min(limit, 200))})


@mcp.tool()
def count_incidents(service: str = "", status: str = "", priority: str = "",
                    opened_from: str = "", opened_to: str = "") -> dict:
    """Count incidents matching the same optional filters as list_incidents.
    Use this for 'how many' questions instead of counting a list yourself."""
    rows = query(f"select count(*)::int as count from itsm.incidents {WHERE}",
                 _args(service, status, priority, opened_from, opened_to))
    return rows[0]


if __name__ == "__main__":
    mcp.run()  # stdio: the agent starts this process and talks to it