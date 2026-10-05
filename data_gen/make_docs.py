"""Writes supabase/DATA_V2.md (the data dictionary) from the generator, so the scenario and edge-case lists never drift.

    python data_gen/make_docs.py
"""
from pathlib import Path

from generate_v2 import build

ROOT = Path(__file__).resolve().parent.parent
tb = build()


def cell(x):
    return str(x if x is not None else "").replace("|", "\\|").replace("\n", " ")


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


counts = [(k, f"{len(v):,}") for k, v in tb.items()]
scen = [(r[0], r[1], ", ".join(r[3]), str(r[4])[:16].replace("T", " "), ", ".join(r[8]) or "none", r[6], r[11]) for r in tb["evalmeta.scenarios"]]
edges = [(r[0], r[1], f"{r[2]} / {r[3]}", r[5]) for r in tb["evalmeta.edge_cases"]]

md = f"""# Overwatch Mini database, version 2

A bigger, harder mock of the three systems Overwatch reads: **itsm** (ServiceNow), **logs** (Splunk) and **metrics**
(Dynatrace). A fourth schema, **evalmeta**, holds the ground truth for evals and is never read by an agent tool.

The window is **1 to 30 September 2026, UTC**, so "last week" questions have enough history. Everything is seeded: the same
code gives the same rows every time.

## Load it

```powershell
python data_gen/load_db.py          # asks first; it DROPS and recreates the tables
python data_gen/check_v2.py         # about 50 checks: links, times, each scenario's signal, edge rows, the existing tools
```

It uses `DATABASE_URL` from `.env` (the Supabase **Session pooler** string). It does not use the SQL Editor, because
the data is about 59,000 rows. `python data_gen/load_db.py --csv-dir out` writes CSV files instead and touches no database.
To change anything, edit `data_gen/generate_v2.py` and `supabase/schema_v2.sql`, then load again.

## What is in it

{table(["table", "rows"], counts)}

| schema.table | what it is | notes |
|---|---|---|
| `itsm.services` | the CMDB: tier, owner team, **aliases** (other names people use) | `legacy-reports` is decommissioned and has no data; `loyalty` is healthy and has no incidents |
| `itsm.service_dependencies` | service X needs service Y (`hard` or `soft`) | checkout hard-depends on auth, payments and inventory. This is the graph for Neo4j later |
| `itsm.changes` | deployments and config changes | state can be implemented, failed, rolled_back, cancelled or scheduled (3 in the future); one is a maintenance window |
| `itsm.incidents` | the incidents. Keeps v1 columns, adds category, source, customer_impact_count, parent_incident_id, reopened_count, closed_reason, change_id | `priority` is the **current** priority |
| `itsm.incident_updates` | the timeline: created, reassignment, status_change, priority_change, work_note, resolution | the only place the original priority and reopen history live |
| `logs.entries` | log lines. Keeps v1 columns, adds host and trace_id | levels include DEBUG and FATAL |
| `metrics.problems` | problems the monitoring tool raised | `related_incident_id` is null when nobody opened an incident |
| `metrics.samples` | cpu, memory, p95 latency, error rate, requests per minute, per service every 15 minutes | all five are **null** (not zero) during a monitoring gap |
| `evalmeta.scenarios`, `evalmeta.edge_cases` | ground truth, below | agents must never see these |

The incident ids `INC0428`, `INC0431` and `INC0433` from version 1 are kept with the same story, so the first demo questions still work.
The existing itsm and logs MCP tools run unchanged on the new tables.

## Planted scenarios

Each one is a story where the change, the incident, the log lines and the metrics all agree. They are in `evalmeta.scenarios`.

{table(["id", "title", "services", "starts (UTC)", "incidents", "root cause (truth)", "what it tests"], scen)}

Random incidents, problems, changes and ERROR noise are kept out of each scenario's window and service (plus one hour either side),
so the story is not muddied by chance.

## Awkward rows

Deliberate edge cases, in `evalmeta.edge_cases`, each with the behaviour we expect from the agent.

{table(["id", "tag", "where", "expected behaviour"], edges)}

## Things the tool writers should know

- **Statuses and levels beyond the tool descriptions.** The v1 tools say status is open, in_progress or resolved and level is ERROR, WARN or INFO.
  The data also has status `on_hold` and levels `DEBUG` and `FATAL`. Decide on purpose: either update the tool descriptions, or leave one undocumented to test whether the agent finds it.
- **`search_logs` caps at 200 rows.** The alert storm (notifications, 20 Sept, 18:00 to 18:30) has more than 200 ERROR lines.
  Counts must come from `count_logs`.
- **Time is half-open: start inclusive, end exclusive, all UTC.** The boundary rows exist to catch off-by-one-day mistakes.
- **Not every problem is an incident, and not every incident has a problem.** Join through `related_incident_id`, and expect nulls.
- **The root cause is often null on purpose.** Open incidents, duplicates, cannot-reproduce and workaround closures have none.

## Not done yet

- The metrics MCP tools (and the merged observability server) do not exist yet. Nothing reads `metrics.*` or `itsm.changes` yet.
- `eval/golden_dataset.jsonl` still describes the **version 1** data, so `eval/verify_golden.py` will fail against this database.
  The golden set needs regenerating from these tables and `evalmeta`.
"""
(ROOT / "supabase" / "DATA_V2.md").write_text(md, encoding="utf-8")
print("wrote supabase/DATA_V2.md", len(md), "characters")
