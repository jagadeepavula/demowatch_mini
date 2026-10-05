"""Runs the golden questions against the live chatbot and scores the answers.

    python eval/run_eval.py --url https://YOUR-SERVICE.run.app
    python eval/run_eval.py --url http://localhost:8080 --workers 2 --category cross_source

Each question gets a fresh conversation. Checks per question (all rule-based, no AI judge yet):
  facts   every fact in must_include appears in the reply   (a list means "any of these")
  clean   nothing from must_not_include appears (catches made-up details and leaked secrets)
  tools   the expected MCP tools were called                 (from the "steps" the API returns)
  agents  the expected specialist agents were used
A question PASSES when facts and clean are both true. tools/agents are reported separately.
"""
import argparse
import json
import statistics
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import has

ROOT = Path(__file__).resolve().parent.parent


def ask(url, question, timeout=120):
    body = json.dumps({"message": question}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/chat", body, {"content-type": "application/json"})
    last = None
    for attempt in range(2):                      # one retry for a cold start or a rate-limit blip
        try:
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            return data, time.time() - t0, None
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(2)
    return {"reply": "", "steps": []}, 0.0, last


def score(g, data):
    reply = data.get("reply", "")
    steps = data.get("steps", [])
    called = {s["call"] for s in steps}
    agents = {s["agent"] for s in steps}
    facts = all(has(reply, f) for f in g["must_include"])
    clean = not any(has(reply, x) for x in g["must_not_include"])
    tools = all(any(t in called for t in (alt if isinstance(alt, list) else [alt])) for alt in g["expected_tools"])
    ag = all(a in agents for a in g["expected_agents"])
    return facts, clean, tools, ag


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--dataset", default=str(ROOT / "eval" / "golden_dataset.jsonl"))
    p.add_argument("--workers", type=int, default=3, help="parallel questions (watch Gemini rate limits)")
    p.add_argument("--category", default="")
    p.add_argument("--out", default="")
    a = p.parse_args()

    cases = [json.loads(l) for l in open(a.dataset)]
    if a.category:
        cases = [c for c in cases if c["category"] == a.category]
    t_start = time.time()

    def run(g):
        data, secs, err = ask(a.url, g["question"])
        facts, clean, tools, ag = score(g, data)
        return {"id": g["id"], "category": g["category"], "difficulty": g["difficulty"], "question": g["question"],
                "expected": g["expected_answer"], "reply": data.get("reply", ""), "steps": data.get("steps", []),
                "facts": facts, "clean": clean, "tools": tools, "agents": ag, "passed": facts and clean,
                "seconds": round(secs, 2), "error": err}

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        results = list(ex.map(run, cases))
    wall = time.time() - t_start

    out = a.out or str(ROOT / "eval" / f"results_{time.strftime('%Y%m%d_%H%M%S')}.jsonl")
    with open(out, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    by = defaultdict(list)
    for r in results:
        by[r["category"]].append(r)
    print(f"\n{'category':<14}{'n':>3}{'pass':>7}{'tools':>7}{'agents':>8}{'avg s':>8}")
    for cat, rs in by.items():
        pct = lambda k: f"{100 * sum(x[k] for x in rs) / len(rs):.0f}%"
        print(f"{cat:<14}{len(rs):>3}{pct('passed'):>7}{pct('tools'):>7}{pct('agents'):>8}"
              f"{statistics.mean(x['seconds'] for x in rs):>8.1f}")
    n_pass = sum(r["passed"] for r in results)
    secs = sorted(r["seconds"] for r in results)
    p95 = secs[min(len(secs) - 1, int(0.95 * len(secs)))]
    print(f"\nPASS {n_pass}/{len(results)} ({100 * n_pass / len(results):.0f}%)  |  "
          f"wall time {wall:.0f}s with {a.workers} workers  |  per-question avg {statistics.mean(secs):.1f}s, p95 {p95:.1f}s")
    print(f"details: {out}")
    for r in results:
        if not r["passed"]:
            why = "request failed: " + r["error"] if r["error"] else f"facts={r['facts']} clean={r['clean']}"
            print(f"\nFAIL {r['id']} [{r['category']}] {r['question']}\n  {why}\n  expected: {r['expected']}\n  got:      {r['reply'][:300]}")


if __name__ == "__main__":
    main()
