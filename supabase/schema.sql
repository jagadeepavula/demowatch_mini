-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.
-- Two schemas in one free project stand in for two separate systems:
--   itsm  = mock ServiceNow (incidents)
--   logs  = mock Splunk (log lines)

create schema if not exists itsm;
create schema if not exists logs;

drop table if exists itsm.incidents;
create table itsm.incidents (
  incident_id text primary key,
  priority    text not null,      -- P1 (worst) .. P4
  service     text not null,
  status      text not null,      -- open | resolved
  summary     text not null,
  opened_at   timestamptz not null
);

drop table if exists logs.entries;
create table logs.entries (
  id      bigint generated always as identity primary key,
  ts      timestamptz not null,
  service text not null,
  level   text not null,          -- ERROR | WARN | INFO
  message text not null
);
create index on logs.entries (service, ts desc);

insert into itsm.incidents values
  ('INC0428','P1','payments','open',    'Payments API returning 5xx',         '2026-09-30 01:10+00'),
  ('INC0431','P3','checkout','resolved','Checkout latency spike overnight',   '2026-09-29 23:40+00'),
  ('INC0433','P2','search',  'open',    'Search results slow for some users', '2026-09-30 08:15+00');

insert into logs.entries (ts, service, level, message) values
  ('2026-09-30 01:12+00','payments','ERROR','503 upstream unavailable pod=payments-7f9'),
  ('2026-09-30 02:55+00','payments','ERROR','503 upstream unavailable pod=payments-7f9'),
  ('2026-09-30 03:10+00','payments','INFO', 'restart requested by on-call'),
  ('2026-09-30 02:04+00','checkout','ERROR','db connection pool exhausted (max=50)'),
  ('2026-09-30 02:09+00','checkout','INFO', 'pool recovered'),
  ('2026-09-30 09:00+00','search',  'INFO', 'healthy, p95=180ms'),
  ('2026-09-30 09:20+00','search',  'WARN', 'p95=920ms, index shard 3 slow');

-- Supabase exposes tables in the "public" schema through its REST API by default.
-- Ours are in other schemas, so they stay private to direct database connections.
