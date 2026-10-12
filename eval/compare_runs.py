"""Compares two saved runs, question by question. This is the before/after view.

    python eval/compare_runs.py baseline after_prompt_fix
    python eval/compare_runs.py baseline after_prompt_fix --metric outcome

A question's score in a run is the share of its trials that passed (so 3 trials -> 0, 0.33, 0.67 or 1).
Prints what got fixed, what broke (a regression), and the change by category.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name, metric):
    rows = [json.loads(l) for l in open(ROOT / "eval" / "runs" / name / "results.jsonl", encoding="utf-8")]
    per = defaultdict(list)
    cat = {}
    for r in rows:
        per[r["id"]].append(1 if r[metric] else 0)
        cat[r["id"]] = r["category"]
    return {k: sum(v) / len(v) for k, v in per.items()}, cat


def main():
    p = argparse.ArgumentParser()
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--metric", default="strict", choices=["strict", "outcome", "trajectory"])
    a = p.parse_args()
    b, cat = load(a.before, a.metric)
    n, _ = load(a.after, a.metric)
    common = sorted(set(b) & set(n))
    fixed = [q for q in common if n[q] > b[q]]
    broke = [q for q in common if n[q] < b[q]]
    print(f"{a.before} -> {a.after}   metric: {a.metric}   questions in both: {len(common)}")
    print(f"before {sum(b[q] for q in common) / len(common):.0%}   after {sum(n[q] for q in common) / len(common):.0%}")
    print(f"\nFIXED ({len(fixed)}): " + (", ".join(f"{q} {b[q]:.0%}->{n[q]:.0%}" for q in fixed) or "none"))
    print(f"BROKE ({len(broke)}): " + (", ".join(f"{q} {b[q]:.0%}->{n[q]:.0%}" for q in broke) or "none") +
          ("   <-- regressions, look at these first" if broke else ""))
    print(f"\n{'category':<14}{'n':>4}{'before':>8}{'after':>8}")
    groups = defaultdict(list)
    for q in common:
        groups[cat[q]].append(q)
    for c, qs in groups.items():
        print(f"{c:<14}{len(qs):>4}{sum(b[q] for q in qs) / len(qs):>8.0%}{sum(n[q] for q in qs) / len(qs):>8.0%}")


if __name__ == "__main__":
    main()