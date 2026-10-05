-- Overwatch Mini database, version 2.
-- Four schemas: itsm (mock ServiceNow), logs (mock Splunk), metrics (mock Dynatrace), evalmeta (ground truth for evals).
-- Loaded by:  python data_gen/load_db.py      (it runs this file, then copies the generated rows in)
-- Safe to re-run: it drops and recreates every table below, including the v1 tables itsm.incidents and logs.entries.

create schema if not exists itsm;
create schema if not exists logs;
create schema if not exists metrics;
create schema if not exists evalmeta;

drop table if exists evalmeta.edge_cases, evalmeta.scenarios cascade;
drop table if exists metrics.samples, metrics.problems cascade;
drop table if exists logs.entries cascade;
drop table if exists itsm.incident_updates, itsm.incidents, itsm.changes, itsm.service_dependencies, itsm.services cascade;

-- ---------------------------------------------------------------- itsm (mock ServiceNow)
create table itsm.services (          -- the CMDB: what services exist and who owns them
  service      text primary key,
  display_name text not null,
  tier         int  not null check (tier between 1 and 3),   -- 1 = most business critical
  owner_team   text not null,
  business_unit text not null,
  description  text not null,
  aliases      text[] not null default '{}',                 -- other names people use for the service
  lifecycle    text not null check (lifecycle in ('active', 'decommissioned'))
);

create table itsm.service_dependencies (   -- service X needs service Y (the graph we may move to Neo4j later)
  service    text not null references itsm.services,
  depends_on text not null references itsm.services,
  kind       text not null check (kind in ('hard', 'soft')),  -- hard = X fails when Y fails
  primary key (service, depends_on)
);

create table itsm.changes (
  change_id    text primary key,                              -- CHG0001 ...
  service      text not null references itsm.services,
  change_type  text not null check (change_type in ('standard', 'normal', 'emergency')),
  state        text not null check (state in ('scheduled', 'implemented', 'failed', 'rolled_back', 'cancelled')),
  risk         text not null check (risk in ('low', 'medium', 'high')),
  summary      text not null,
  planned_start timestamptz not null,
  planned_end   timestamptz not null,
  actual_start  timestamptz,                                  -- null if never started
  actual_end    timestamptz,
  implemented_by text not null,
  is_maintenance_window boolean not null default false        -- planned downtime: errors are expected
);

create table itsm.incidents (
  incident_id      text primary key,
  priority         text not null check (priority in ('P1', 'P2', 'P3', 'P4')),   -- P1 = worst; this is the CURRENT priority
  service          text not null references itsm.services,
  status           text not null check (status in ('open', 'in_progress', 'on_hold', 'resolved')),
  summary          text not null,
  opened_at        timestamptz not null,
  resolved_at      timestamptz,                               -- null unless status = resolved (a reopened incident clears it)
  assignment_group text not null,
  root_cause       text,                                      -- often null: open, duplicates, cannot-reproduce, workarounds
  category         text not null,
  source           text not null check (source in ('monitoring', 'customer_report', 'engineer', 'synthetic_check')),
  customer_impact_count int,                                  -- null = unknown, 0 = known to be none
  parent_incident_id text references itsm.incidents,          -- duplicate of, or caused by, another incident
  reopened_count   int not null default 0,
  closed_reason    text check (closed_reason in ('fixed', 'duplicate', 'cannot_reproduce', 'workaround', 'auto_resolved')),
  change_id        text references itsm.changes,              -- the change recorded as the cause, when known
  constraint resolved_consistent check ((status = 'resolved') = (resolved_at is not null)),
  constraint resolved_after_open check (resolved_at is null or resolved_at >= opened_at)
);

create table itsm.incident_updates (   -- the timeline of each incident
  update_id   bigint generated always as identity primary key,
  incident_id text not null references itsm.incidents,
  ts          timestamptz not null,
  author      text not null,
  kind        text not null check (kind in ('created', 'reassignment', 'status_change', 'priority_change', 'work_note', 'resolution')),
  old_value   text,
  new_value   text,
  note        text
);

-- ---------------------------------------------------------------- logs (mock Splunk)
create table logs.entries (
  id       bigint generated always as identity primary key,
  ts       timestamptz not null,
  service  text not null references itsm.services,
  level    text not null check (level in ('DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL')),
  message  text not null,
  host     text not null,
  trace_id text
);

-- ---------------------------------------------------------------- metrics (mock Dynatrace)
create table metrics.problems (
  problem_id text primary key,                                -- P-2026-0001 ...
  service    text not null references itsm.services,
  severity   text not null check (severity in ('AVAILABILITY', 'ERROR', 'PERFORMANCE', 'RESOURCE')),
  status     text not null check (status in ('open', 'closed')),
  title      text not null,
  started_at timestamptz not null,
  ended_at   timestamptz,
  root_cause_entity text,
  related_incident_id text references itsm.incidents          -- null = monitoring raised it but nobody opened an incident
);

create table metrics.samples (          -- one row per service per 15 minutes
  ts      timestamptz not null,
  service text not null references itsm.services,
  cpu_pct numeric(5, 2),                -- all five values are null when monitoring had a gap
  memory_pct numeric(5, 2),
  latency_p95_ms numeric(9, 1),
  error_rate_pct numeric(6, 2),
  requests_per_min numeric(9, 1),
  primary key (service, ts)
);

-- ---------------------------------------------------------------- evalmeta (ground truth; no agent tool reads this)
create table evalmeta.scenarios (       -- planted stories that span incidents, changes, logs and metrics
  scenario_id text primary key,
  title       text not null,
  shape       text not null,
  services    text[] not null,
  starts_at   timestamptz not null,
  ends_at     timestamptz,
  root_cause_truth text not null,
  change_ids   text[] not null default '{}',
  incident_ids text[] not null default '{}',
  problem_ids  text[] not null default '{}',
  description  text not null,
  what_it_tests text not null
);

create table evalmeta.edge_cases (      -- deliberately awkward rows, each with the behaviour we expect from the agent
  edge_id   text primary key,
  tag       text not null,
  ref_table text not null,
  ref_key   text not null,
  description text not null,
  expected_behavior text not null
);

-- ---------------------------------------------------------------- indexes
create index on itsm.incidents (service, opened_at desc);
create index on itsm.incidents (status, priority);
create index on itsm.incidents (opened_at);
create index on itsm.incident_updates (incident_id, ts);
create index on itsm.changes (service, planned_start);
create index on logs.entries (service, ts desc);
create index on logs.entries (level, ts);
create index on logs.entries (ts);
create index on metrics.problems (service, started_at);
create index on metrics.samples (ts);

-- ---------------------------------------------------------------- security
-- Lock every table from Supabase's public API keys. Our backend uses the database login, which bypasses this.
alter table itsm.services enable row level security;
alter table itsm.service_dependencies enable row level security;
alter table itsm.changes enable row level security;
alter table itsm.incidents enable row level security;
alter table itsm.incident_updates enable row level security;
alter table logs.entries enable row level security;
alter table metrics.problems enable row level security;
alter table metrics.samples enable row level security;
alter table evalmeta.scenarios enable row level security;
alter table evalmeta.edge_cases enable row level security;
