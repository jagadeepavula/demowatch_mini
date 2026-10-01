"""Tiny shared helper: run a SELECT against Supabase Postgres and return rows as dicts."""
import os
from datetime import timezone
import psycopg
from psycopg.rows import dict_row


def query(sql: str, params: tuple = ()) -> list[dict]:
    url = os.environ["DATABASE_URL"]  # Supabase -> Connect -> Session pooler string
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=10) as con:
        rows = con.execute(sql, params).fetchall()
    # make timestamps JSON-friendly
    def fix(v):  # timestamps -> UTC text so the model sees one consistent clock
        return v.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if hasattr(v, "astimezone") else v
    return [{k: fix(v) for k, v in r.items()} for r in rows]
