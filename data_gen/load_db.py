"""Builds the version 2 dataset and loads it into Postgres (Supabase or a local database).

    python data_gen/load_db.py                 asks before it replaces the tables
    python data_gen/load_db.py --yes           no question
    python data_gen/load_db.py --csv-dir out   only write CSV files, touch no database
    python data_gen/load_db.py --url postgresql://...   use this database instead of DATABASE_URL

It runs supabase/schema_v2.sql first (this DROPS and recreates itsm.incidents, logs.entries and the other tables),
then copies about 60,000 rows in with COPY, which takes seconds. Use the Supabase Session pooler connection string.
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_v2 import COLUMNS, ORDER, build  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="database URL (default: DATABASE_URL from the environment or .env)")
    ap.add_argument("--yes", action="store_true", help="do not ask before replacing the tables")
    ap.add_argument("--csv-dir", help="write one CSV per table to this folder and stop")
    a = ap.parse_args()

    t0 = time.time()
    tables = build()
    print(f"built {sum(len(v) for v in tables.values()):,} rows in {time.time() - t0:.1f}s")

    if a.csv_dir:
        out = Path(a.csv_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name in ORDER:
            with open(out / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([c.strip() for c in COLUMNS[name].split(",")])
                w.writerows(tables[name])
        print(f"wrote {len(ORDER)} CSV files to {out}")
        return

    from dotenv import load_dotenv
    import psycopg

    load_dotenv(ROOT / ".env")
    url = a.url or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("No database: set DATABASE_URL (in .env) or pass --url")
    host = url.split("@")[-1].split("/")[0]
    if not a.yes and input(f"This replaces the tables on {host}. Type yes to continue: ").strip().lower() != "yes":
        sys.exit("cancelled")

    with psycopg.connect(url, connect_timeout=15) as con:
        con.execute((ROOT / "supabase" / "schema_v2.sql").read_text())
        for name in ORDER:
            t = time.time()
            with con.cursor() as cur, cur.copy(f"copy {name} ({COLUMNS[name]}) from stdin") as cp:
                for row in tables[name]:
                    cp.write_row(row)
            print(f"  {name:28s} {len(tables[name]):>7,} rows  {time.time() - t:4.1f}s")
        con.commit()
        con.autocommit = True
        con.execute("analyze")
    print(f"done in {time.time() - t0:.1f}s. Run: python data_gen/check_v2.py")


if __name__ == "__main__":
    main()
