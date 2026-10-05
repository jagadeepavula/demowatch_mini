"""MCP server #2: mock Splunk + Dynatrace in one server. Reads the logs and metrics schemas in Supabase.

Five tools. The logs agent is given the first three and the metrics agent the last two (see ops_agent/agent.py).

Times are UTC. `start` is inclusive and `end` is exclusive, as YYYY-MM-DD or "YYYY-MM-DD HH:MM".
To cover all of 29 September use start=2026-09-29 and end=2026-09-30.
"""
from mcp.server.fastmcp import FastMCP
from db import query

mcp = FastMCP("observability")

LOG_WHERE = (
    "where (%(service)s = '' or service = %(service)s) "
    "and (%(level)s = '' or level = %(level)s) "
    "and (%(s)s = '' or ts >= (nullif(%(s)s,'')::timestamp at time zone 'UTC')) "
    "and (%(e)s = '' or ts <  (nullif(%(e)s,'')::timestamp at time zone 'UTC'))"
)


def _log_args(service, level, start, end):
    return {"service": service.lower().strip(), "level": level.upper().strip(), "s": start.strip(), "e": end.strip()}


# ------------------------------------------------------------------ logs (3 tools)
@mcp.tool()
def search_logs(service: str, level: str = "", start: str = "", end: str = "", limit: int = 20) -> list[dict]:
    """Search application logs for one service, newest first. At most 200 lines come back, so never count by reading them.
    service: payments, checkout, search, auth, inventory, catalog, notifications, shipping, loyalty.
    level (optional): DEBUG, INFO, WARN, ERROR or FATAL. start/end (optional): UTC time range, start inclusive, end exclusive.
    Returns ts, service, level, message, host and trace_id for each line."""
    return query(f"select ts, service, level, message, host, trace_id from logs.entries {LOG_WHERE} "
                 "order by ts desc limit %(limit)s",
                 {**_log_args(service, level, start, end), "limit": max(1, min(limit, 200))})


@mcp.tool()
def count_logs(service: str = "", level: str = "", start: str = "", end: str = "") -> dict:
    """Count log lines with the same optional filters as search_logs (service may be left empty for all services).
    Use this for 'how many' questions."""
    return query(f"select count(*)::int as count from logs.entries {LOG_WHERE}", _log_args(service, level, start, end))[0]


@mcp.tool()
def error_counts_by_service(start: str = "", end: str = "") -> list[dict]:
    """For each service, the number of FATAL, ERROR and WARN lines in the time range, most errors first.
    Use this to find which service has the most errors."""
    return query(
        "select service, count(*) filter (where level='ERROR')::int as errors, "
        "count(*) filter (where level='FATAL')::int as fatal, "
        "count(*) filter (where level='WARN')::int as warnings from logs.entries "
        "where (%(s)s = '' or ts >= (nullif(%(s)s,'')::timestamp at time zone 'UTC')) "
        "and (%(e)s = '' or ts < (nullif(%(e)s,'')::timestamp at time zone 'UTC')) "
        "group by service order by errors desc, fatal desc, service",
        {"s": start.strip(), "e": end.strip()})


# ------------------------------------------------------------------ metrics (2 tools)
@mcp.tool()
def get_metrics(service: str, start: str, end: str, granularity: str = "summary") -> list[dict]:
    """Performance numbers for one service over a UTC time range (start inclusive, end exclusive).
    Metrics: cpu_pct, memory_pct, latency_p95_ms, error_rate_pct (percent of requests failing), requests_per_min.
    One reading is taken every 15 minutes. A reading is missing (null) when monitoring had a gap; that is not the same as zero.
    granularity: 'summary' (default, one row: averages, maxima, samples and missing_samples),
    'hourly' (one row per hour with averages and maxima) or '15min' (raw readings, newest first, at most 200).
    service: payments, checkout, search, auth, inventory, catalog, notifications, shipping, loyalty."""
    q = {"service": service.lower().strip(), "s": start.strip(), "e": end.strip()}
    base = ("from metrics.samples where service = %(service)s "
            "and ts >= (nullif(%(s)s,'')::timestamp at time zone 'UTC') "
            "and ts <  (nullif(%(e)s,'')::timestamp at time zone 'UTC')")
    g = granularity.lower().strip()
    if g in ("15min", "raw"):
        return query("select ts, cpu_pct::float, memory_pct::float, latency_p95_ms::float, error_rate_pct::float, "
                     f"requests_per_min::float {base} order by ts desc limit 200", q)
    agg = ("round(avg(cpu_pct),1)::float as avg_cpu_pct, round(max(cpu_pct),1)::float as max_cpu_pct, "
           "round(avg(memory_pct),1)::float as avg_memory_pct, round(max(memory_pct),1)::float as max_memory_pct, "
           "round(avg(latency_p95_ms),0)::float as avg_latency_p95_ms, round(max(latency_p95_ms),0)::float as max_latency_p95_ms, "
           "round(avg(error_rate_pct),2)::float as avg_error_rate_pct, round(max(error_rate_pct),2)::float as max_error_rate_pct, "
           "round(avg(requests_per_min),0)::float as avg_requests_per_min, "
           "count(*)::int as samples, (count(*) - count(cpu_pct))::int as missing_samples")
    if g == "hourly":
        return query(f"select date_trunc('hour', ts) as hour, {agg} {base} group by 1 order by 1 limit 200", q)
    return query(f"select %(service)s as service, {agg} {base}", q)


@mcp.tool()
def list_problems(service: str = "", status: str = "", severity: str = "", start: str = "", end: str = "",
                  limit: int = 50) -> list[dict]:
    """List problems the monitoring tool raised, newest first. A problem is not an incident: monitoring can raise
    a problem that nobody turned into an incident (related_incident_id is then null).
    status: open or closed. severity: AVAILABILITY, ERROR, PERFORMANCE or RESOURCE.
    start/end filter on when the problem started (UTC, start inclusive, end exclusive). All filters are optional.
    Returns problem_id, service, severity, status, title, started_at, ended_at, root_cause_entity, related_incident_id."""
    return query(
        "select problem_id, service, severity, status, title, started_at, ended_at, root_cause_entity, related_incident_id "
        "from metrics.problems "
        "where (%(service)s = '' or service = %(service)s) and (%(status)s = '' or status = %(status)s) "
        "and (%(sev)s = '' or severity = %(sev)s) "
        "and (%(s)s = '' or started_at >= (nullif(%(s)s,'')::timestamp at time zone 'UTC')) "
        "and (%(e)s = '' or started_at <  (nullif(%(e)s,'')::timestamp at time zone 'UTC')) "
        "order by started_at desc limit %(limit)s",
        {"service": service.lower().strip(), "status": status.lower().strip(), "sev": severity.upper().strip(),
         "s": start.strip(), "e": end.strip(), "limit": max(1, min(limit, 200))})


if __name__ == "__main__":
    mcp.run()
