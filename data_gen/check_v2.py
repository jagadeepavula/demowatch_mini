"""Checks the loaded version 2 database. No AI model involved: plain SQL against the tables.

    python data_gen/check_v2.py                   uses DATABASE_URL from .env
    python data_gen/check_v2.py --url postgresql://...

It confirms three things:
  1. integrity: every link between tables holds, times make sense, row counts are what the generator makes
  2. stories: each planted scenario really shows up in the incidents, logs and metrics (the signal is there)
  3. awkward rows: each edge case in evalmeta.edge_cases exists, and the existing MCP tools still work on the new tables
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
ap = argparse.ArgumentParser()
ap.add_argument("--url")
args = ap.parse_args()
URL = args.url or os.environ.get("DATABASE_URL") or sys.exit("Set DATABASE_URL or pass --url")
con = psycopg.connect(URL, connect_timeout=15)
bad = 0


def one(sql, *p):
    return con.execute(sql, p or None).fetchone()[0]


def check(name, ok, detail=""):
    global bad
    bad += not ok
    print(("ok   " if ok else "FAIL ") + name + (f"   [{detail}]" if detail or not ok else ""))


print("== 1. integrity")
counts = {"itsm.services": 10, "itsm.changes": 100, "itsm.incidents": 400, "itsm.incident_updates": 2000, "logs.entries": 25000,
          "metrics.problems": 80, "metrics.samples": 25920, "evalmeta.scenarios": 15, "evalmeta.edge_cases": 15}
for t, minimum in counts.items():
    n = one(f"select count(*) from {t}")
    check(f"{t} has at least {minimum} rows", n >= minimum, n)
check("every incident has a 'created' update", one("select count(*) from itsm.incidents i where not exists (select 1 from itsm.incident_updates u where u.incident_id = i.incident_id and u.kind = 'created')") == 0)
check("no update before its incident opened", one("select count(*) from itsm.incident_updates u join itsm.incidents i using (incident_id) where u.ts < i.opened_at") == 0)
check("no update after the data window", one("select count(*) from itsm.incident_updates where ts >= '2026-10-01+00'") == 0)
check("every resolved incident has a resolution update", one("select count(*) from itsm.incidents i where status = 'resolved' and not exists (select 1 from itsm.incident_updates u where u.incident_id = i.incident_id and u.kind = 'resolution')") == 0)
check("closed problems end after they start", one("select count(*) from metrics.problems where status = 'closed' and (ended_at is null or ended_at < started_at)") == 0)
check("open problems have no end", one("select count(*) from metrics.problems where status = 'open' and ended_at is not null") == 0)
check("child incidents never open before their parent", one("select count(*) from itsm.incidents c join itsm.incidents p on p.incident_id = c.parent_incident_id where c.opened_at < p.opened_at") == 0)
check("each service has 2880 samples", one("select count(distinct service) from metrics.samples") == 9 and one("select min(c) = max(c) from (select count(*) c from metrics.samples group by service) x"))
check("legacy-reports has no data anywhere", one("select (select count(*) from logs.entries where service = 'legacy-reports') + (select count(*) from itsm.incidents where service = 'legacy-reports') + (select count(*) from metrics.samples where service = 'legacy-reports')") == 0)
check("loyalty has no incidents and no ERROR/WARN/FATAL logs", one("select (select count(*) from itsm.incidents where service = 'loyalty') + (select count(*) from logs.entries where service = 'loyalty' and level <> 'INFO')") == 0)
check("incident ids INC0428, INC0431, INC0433 exist", one("select count(*) from itsm.incidents where incident_id in ('INC0428','INC0431','INC0433')") == 3)

print("\n== 2. planted stories")
d = lambda sql: one(sql)
check("S01 payments error rate is high after the bad deploy and normal before",
      d("select avg(error_rate_pct) from metrics.samples where service='payments' and ts >= '2026-09-30 02:00+00' and ts < '2026-09-30 05:00+00'") > 5
      and d("select avg(error_rate_pct) from metrics.samples where service='payments' and ts >= '2026-09-29 02:00+00' and ts < '2026-09-29 05:00+00'") < 1)
check("S01 a payments change precedes INC0428 and the incident has no root cause",
      d("select count(*) from itsm.changes c, itsm.incidents i where i.incident_id='INC0428' and c.service='payments' and c.actual_end <= i.opened_at and c.actual_end > i.opened_at - interval '1 hour'") >= 1
      and d("select count(*) from itsm.incidents where incident_id='INC0428' and root_cause is null and change_id is null and status='open'") == 1)
check("S02 INC0431 links its change and has a root cause", d("select count(*) from itsm.incidents where incident_id='INC0431' and change_id is not null and root_cause = 'Database connection pool too small' and status='resolved'") == 1)
check("S03 search is slow at 08:30 and 09:30 but not at 09:00 (flapping)",
      d("select min(latency_p95_ms) from metrics.samples where service='search' and ts in ('2026-09-30 08:30+00','2026-09-30 09:30+00')") > 450
      and d("select latency_p95_ms from metrics.samples where service='search' and ts = '2026-09-30 09:00+00'") < 300)
check("S04 auth FATAL burst and downstream errors", d("select count(*) from logs.entries where service='auth' and level='FATAL' and ts >= '2026-09-12 14:05+00' and ts < '2026-09-12 14:52+00'") >= 50
      and d("select count(*) from logs.entries where service in ('checkout','payments') and level='ERROR' and ts >= '2026-09-12 14:08+00' and ts < '2026-09-12 14:57+00'") >= 60)
check("S04 two child incidents point at the auth incident", d("select count(*) from itsm.incidents c join itsm.incidents p on p.incident_id = c.parent_incident_id where p.service='auth' and p.opened_at = '2026-09-12 14:05+00'") == 2)
check("S05 duplicate pair: same summary, one closed as duplicate with no root cause", d("select count(*) from itsm.incidents where closed_reason='duplicate' and root_cause is null and parent_incident_id is not null and summary = 'Search returns no results for common terms'") == 1)
check("S06 reopened incident: count 1 and a resolved->open update", d("select count(*) from itsm.incidents i where reopened_count = 1 and exists (select 1 from itsm.incident_updates u where u.incident_id=i.incident_id and u.old_value='resolved' and u.new_value='open')") == 1)
check("S07 escalation: current P1, history P3 -> P2 -> P1", d("select count(*) from itsm.incidents i where priority='P1' and summary='Negative stock levels reported' and (select count(*) from itsm.incident_updates u where u.incident_id=i.incident_id and u.kind='priority_change') = 2") == 1)
check("S08 silent failure: notifications errors and a problem on 18 Sept, no incident",
      d("select count(*) from logs.entries where service='notifications' and level='ERROR' and ts >= '2026-09-18 13:00+00' and ts < '2026-09-18 14:10+00'") >= 20
      and d("select count(*) from metrics.problems where service='notifications' and started_at >= '2026-09-18 12:00+00' and started_at < '2026-09-18 15:00+00' and related_incident_id is null") == 1
      and d("select count(*) from itsm.incidents where service='notifications' and opened_at >= '2026-09-18 12:00+00' and opened_at < '2026-09-18 15:10+00'") == 0)
check("S09 catalog on 19 Sept: WARN lines only, no ERROR lines, incident exists",
      d("select count(*) from logs.entries where service='catalog' and level='WARN' and message like 'price feed row%' and ts >= '2026-09-19+00' and ts < '2026-09-20+00'") >= 20
      and d("select count(*) from logs.entries where service='catalog' and level in ('ERROR','FATAL') and ts >= '2026-09-19 08:30+00' and ts < '2026-09-19 15:20+00'") == 0
      and d("select count(*) from itsm.incidents where summary='Wrong prices displayed'") >= 1)
check("S10 inventory gap: no logs and null metrics 03:00-06:00 on 21 Sept",
      d("select count(*) from logs.entries where service='inventory' and ts >= '2026-09-21 03:00+00' and ts < '2026-09-21 06:00+00'") == 0
      and d("select count(*) from metrics.samples where service='inventory' and ts >= '2026-09-21 03:00+00' and ts < '2026-09-21 06:00+00' and cpu_pct is null") == 12)
check("S11 rolled back emergency change on checkout, no incident that day", d("select count(*) from itsm.changes where service='checkout' and state='rolled_back' and change_type='emergency' and planned_start::date='2026-09-22'") == 1
      and d("select count(*) from itsm.incidents where service='checkout' and opened_at >= '2026-09-22 15:00+00' and opened_at < '2026-09-22 18:00+00'") == 0)
check("S12 catalog memory climbs over two days", d("select avg(memory_pct) from metrics.samples where service='catalog' and ts >= '2026-09-25 04:00+00' and ts < '2026-09-25 05:45+00'")
      - d("select avg(memory_pct) from metrics.samples where service='catalog' and ts >= '2026-09-22 04:00+00' and ts < '2026-09-22 05:45+00'") > 25)
check("S13 maintenance window: change flagged, ERRORs inside it, no incident", d("select count(*) from itsm.changes where is_maintenance_window") == 1
      and d("select count(*) from logs.entries where service='shipping' and level='ERROR' and ts >= '2026-09-27 02:00+00' and ts < '2026-09-27 03:50+00'") >= 15)
check("S14 traffic spike: checkout requests more than double the same hour a day later",
      d("select avg(requests_per_min) from metrics.samples where service='checkout' and ts >= '2026-09-14 12:00+00' and ts < '2026-09-14 15:00+00'")
      > 2 * d("select avg(requests_per_min) from metrics.samples where service='checkout' and ts >= '2026-09-15 12:00+00' and ts < '2026-09-15 15:00+00'"))
n = d("select count(*) from logs.entries where service='notifications' and level='ERROR' and ts >= '2026-09-20 18:00+00' and ts < '2026-09-20 18:30+00'")
check("S15 alert storm is over the 200-row tool limit", n > 200, n)

print("\n== 3. awkward rows and the existing tools")
refs = con.execute("select edge_id, tag, ref_table, ref_key from evalmeta.edge_cases").fetchall()
for edge_id, tag, table, key in refs:
    if table == "logs.entries":
        svc, ts = key.split("@")
        ok = one("select count(*) from logs.entries where service = %s and ts = %s::timestamptz", svc, ts + "+00") >= 1
    elif table == "itsm.incidents":
        ok = one("select count(*) from itsm.incidents where incident_id = %s", key) == 1
    elif table == "itsm.incident_updates":
        ok = one("select count(*) from itsm.incident_updates where incident_id = %s and kind = 'work_note'", key) >= 1
    else:
        ok = one("select count(*) from itsm.services where service = %s", key) == 1
    check(f"edge {edge_id} {tag}", ok)

os.environ["DATABASE_URL"] = URL
sys.path.insert(0, str(ROOT / "mcp_servers"))
try:
    import itsm_server, observability_server as logs_server
    r = itsm_server.get_incident("INC0428")
    check("tool get_incident('INC0428') still works", r.get("status") == "open" and r.get("priority") == "P1" and r.get("service") == "payments", {k: r.get(k) for k in ("status", "priority")})
    check("tool list_incidents(service=payments, status=open) includes INC0428", any(x["incident_id"] == "INC0428" for x in itsm_server.list_incidents(service="payments", status="open")))
    check("tool count_incidents() matches the table", itsm_server.count_incidents()["count"] == one("select count(*) from itsm.incidents"))
    check("tool search_logs works", len(logs_server.search_logs("payments", level="ERROR", limit=5)) == 5)
    check("tool count_logs works", logs_server.count_logs(service="notifications", level="ERROR", start="2026-09-20 18:00", end="2026-09-20 18:30")["count"] == n)
    check("tool error_counts_by_service works", len(logs_server.error_counts_by_service("2026-09-30", "2026-10-01")) >= 5)
    check("search_logs caps at 200 rows (so the storm cannot be counted by reading rows)", len(logs_server.search_logs("notifications", level="ERROR", start="2026-09-20", end="2026-09-21", limit=500)) == 200)
    m = logs_server.get_metrics("payments", "2026-09-30 02:00", "2026-09-30 05:00")[0]
    check("tool get_metrics summary shows the S01 error rate", m["avg_error_rate_pct"] > 5 and m["samples"] == 12 and m["missing_samples"] == 0, m["avg_error_rate_pct"])
    g = logs_server.get_metrics("inventory", "2026-09-21 02:00", "2026-09-21 07:00")[0]
    check("tool get_metrics reports the S10 gap as missing samples, not zeros", g["missing_samples"] == 12 and g["samples"] == 20, g["missing_samples"])
    check("tool get_metrics hourly returns one row per hour", len(logs_server.get_metrics("checkout", "2026-09-14 12:00", "2026-09-14 15:00", "hourly")) == 3)
    check("tool get_metrics 15min returns raw readings", len(logs_server.get_metrics("checkout", "2026-09-14 12:00", "2026-09-14 13:00", "15min")) == 4)
    pr = logs_server.list_problems(service="notifications", start="2026-09-18", end="2026-09-19")
    check("tool list_problems finds the S08 problem with no incident", any(x["related_incident_id"] is None for x in pr), len(pr))
    check("tool list_problems filters by status", all(x["status"] == "open" for x in logs_server.list_problems(status="open")))
except Exception as e:  # noqa: BLE001
    check("existing MCP tools import and run", False, repr(e))

print(f"\n{'ALL CHECKS PASSED' if not bad else str(bad) + ' CHECK(S) FAILED'}")
sys.exit(1 if bad else 0)
