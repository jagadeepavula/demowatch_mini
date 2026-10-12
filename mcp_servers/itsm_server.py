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
                   opened_from: str = "", opened_to: str = "", limit: int = 50, oldest_first: bool = False) -> list[dict]:
    """List incidents, newest first (or oldest first with oldest_first=true, for 'which has been waiting the longest').
    All filters are optional; leave one empty to skip it.
    service: payments, checkout, search, auth, inventory, catalog, notifications, shipping, loyalty.
    status: open, in_progress, on_hold or resolved. priority: P1 (worst) to P4.
    opened_from / opened_to: UTC dates, from inclusive and to exclusive.
    'Unresolved' means status open, in_progress or on_hold: list each of those and compare."""
    order = "asc" if oldest_first else "desc"
    sql = f"select * from itsm.incidents {WHERE} order by opened_at {order} limit %(limit)s"
    return query(sql, {**_args(service, status, priority, opened_from, opened_to), "limit": max(1, min(limit, 200))})


@mcp.tool()
def count_incidents(service: str = "", status: str = "", priority: str = "",
                    opened_from: str = "", opened_to: str = "") -> dict:
    """Count incidents matching the same optional filters as list_incidents.
    Use this for 'how many' questions instead of counting a list yourself."""
    rows = query(f"select count(*)::int as count from itsm.incidents {WHERE}",
                 _args(service, status, priority, opened_from, opened_to))
    return rows[0]


@mcp.tool()
def count_incidents_by_service(status: str = "", priority: str = "", opened_from: str = "", opened_to: str = "") -> list[dict]:
    """Count incidents per service, highest first. Use this for 'which service has the most incidents'.
    Optional filters: status, priority, opened_from / opened_to (same meaning as in list_incidents)."""
    return query(f"select service, count(*)::int as count from itsm.incidents {WHERE} group by service order by count desc, service",
                 _args("", status, priority, opened_from, opened_to))


@mcp.tool()
def get_related_incidents(incident_id: str) -> dict:
    """Find the incidents linked to one incident: its parent (the incident it duplicates or was caused by)
    and its children (incidents that name it as their parent). Use this for 'what else did it cause'."""
    iid = incident_id.upper().strip()
    me = query("select * from itsm.incidents where incident_id = %s", (iid,))
    if not me:
        return {"found": False, "message": f"No incident {incident_id}"}
    parent = query("select * from itsm.incidents where incident_id = %s", (me[0]["parent_incident_id"],)) if me[0].get("parent_incident_id") else []
    children = query("select * from itsm.incidents where parent_incident_id = %s order by opened_at", (iid,))
    return {"incident_id": iid, "parent": parent[0] if parent else None, "children": children}


if __name__ == "__main__":
    mcp.run()  # stdio: the agent starts this process and talks to it