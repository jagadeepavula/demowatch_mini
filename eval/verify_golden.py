"""Checks the golden dataset against the real database, without any AI model.

For each question it runs the reference tool calls (the same SQL the agent's MCP tools run) and
confirms the expected facts really appear in the data. Two independent computations must agree:
the Python that built the answers, and the SQL that reads the database.

    set DATABASE_URL (or have it in .env), then:   python eval/verify_golden.py
Questions marked "derived" (sums, durations, refusals) only check that the calls run.
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "mcp_servers"))
sys.path.insert(0, str(ROOT / "eval"))
import itsm_server, observability_server as logs_server  # noqa: E402
from common import has  # noqa: E402

MODS = {"itsm": itsm_server, "logs": logs_server, "observability": logs_server}
bad = 0
cases = [json.loads(l) for l in open(ROOT / "eval" / (sys.argv[1] if len(sys.argv) > 1 else "golden_v2.jsonl"), encoding="utf-8")]
for g in cases:
    text, err = "", None
    try:
        for c in g["reference_calls"]:
            out = getattr(MODS[c["server"]], c["tool"])(**c["args"])
            text += json.dumps(out, default=str, ensure_ascii=False) + (f" rows={len(out)} " if isinstance(out, list) else " ")
    except Exception as e:  # noqa: BLE001
        err = e
    missing = [] if g["derived"] else [f for f in g["must_include"] if not has(text, f)]
    ok = err is None and not missing
    bad += not ok
    print(("ok  " if ok else "FAIL"), g["id"], g["category"], "-", g["question"][:70],
          "" if ok else f"-> missing {missing} {err or ''}")
print(f"\n{len(cases) - bad}/{len(cases)} golden cases verified against the database")
sys.exit(1 if bad else 0)