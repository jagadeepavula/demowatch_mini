"""Re-scores a saved run with the current grader. No Gemini calls, no server needed.

    python eval/rescore.py baseline

Use it after you fix a grader bug or a golden expectation: the saved replies and traces stay the same,
only the judging changes. It prints the old and new pass counts and writes failure_detail.txt in the run
folder: for every failed question the reply, the route, the auto tags and what the agent really sent
for each argument that did not match.
"""
import argparse
import json
from pathlib import Path

from run_eval import assign_splits, judge_row

ROOT = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("name")
    p.add_argument("--dataset", default=str(ROOT / "eval" / "golden_v2.jsonl"))
    a = p.parse_args()

    gold = {g["id"]: g for g in assign_splits([json.loads(l) for l in open(a.dataset, encoding="utf-8")])}
    rows = [json.loads(l) for l in open(ROOT / "eval" / "runs" / a.name / "results.jsonl", encoding="utf-8")]

    old = {"outcome": sum(r["outcome"] for r in rows), "strict": sum(r["strict"] for r in rows)}
    lines, new_rows = [], []
    for r in rows:
        g = gold[r["id"]]
        r2 = {**r, **judge_row(g, {"reply": r["reply"], "steps": r["steps"]}, r["error"])}
        new_rows.append(r2)
        if r2["strict"]:
            continue
        route = " > ".join(f"{s['agent']}:{s['call']}" for s in r2["steps"]) or "(no tool calls)"
        lines.append(f"{r2['id']} [{r2['category']}] {r2['question']}\n"
                     f"  tags:    {', '.join(r2['tags'])}\n  route:   {route}\n"
                     f"  args:    {r2['args_diff'] or 'ok'}\n  expect:  {r2['expected']}\n  reply:   {r2['reply'][:900]}\n")

    n = len(rows)
    new = {"outcome": sum(r["outcome"] for r in new_rows), "strict": sum(r["strict"] for r in new_rows)}
    print(f"{a.name}: {n} runs")
    print(f"as run      outcome {old['outcome']}/{n}   strict {old['strict']}/{n}")
    print(f"re-scored   outcome {new['outcome']}/{n}   strict {new['strict']}/{n}")
    flipped = [r["id"] for r, r2 in zip(rows, new_rows) if not r["strict"] and r2["strict"]]
    broke = [r["id"] for r, r2 in zip(rows, new_rows) if r["strict"] and not r2["strict"]]
    print(f"now passing: {', '.join(flipped) or 'none'}")
    print(f"now failing: {', '.join(broke) or 'none'}")
    out = ROOT / "eval" / "runs" / a.name / "failure_detail.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{len(lines)} still failing. details for each: {out}")


if __name__ == "__main__":
    main()