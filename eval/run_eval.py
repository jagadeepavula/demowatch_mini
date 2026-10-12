"""Runs the golden questions against the live chatbot, scores the traces, and saves a run folder.

    python eval/run_eval.py --url https://YOUR-SERVICE.run.app --name baseline
    python eval/run_eval.py --url http://localhost:8080 --name try1 --trials 3 --split dev
    python eval/run_eval.py --url http://localhost:8080 --ids G001,G002 --name smoke

Everything is rule-based (no AI judge yet). Checks per question, each reported on its own:

  OUTCOME (the answer)
    facts    every fact in must_include appears in the reply (a list means "any of these")
    clean    nothing from must_not_include appears (catches made-up details and leaked secrets)
  TRAJECTORY (the route the agents took)
    agents   the expected specialist agents were used            (routing)
    tools    the expected MCP tools were called                  (tool selection)
    args     a call matches each reference call's arguments      (argument accuracy; time strings are normalised)
  RESULT
    outcome  facts and clean
    style    no hand-off narration ("I will now transfer to...")
    strict   outcome and agents and tools and args and style   <- a right answer through the wrong route does not count

Each question can be run several times (--trials) because the model is not deterministic:
  pass@k  at least one trial passed      pass^k  every trial passed (the reliability number)

A run is saved to eval/runs/<name>/ as results.jsonl (one line per question per trial), summary.json,
and failures.csv (one line per failed trial, with an auto tag and an empty human_tag column for you to fill in).
"""
import argparse
import csv
import hashlib
import json
import re
import statistics
import subprocess
import time
import urllib.request
from datetime import datetime
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import forbidden, has

ROOT = Path(__file__).resolve().parent.parent
SKIP_ARGS = {"limit"}                    # how many rows were asked for does not change correctness
NARRATION = re.compile(r"\b(i will now|now i will|i'll now|transfer(ring)? (to|you to)|hand(ing)? (this |it )?over)\b", re.I)


# ------------------------------------------------------------------ calling the chatbot
def ask(url, question, timeout=120):
    body = json.dumps({"message": question}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/chat", body, {"content-type": "application/json"})
    last = None
    for attempt in (1, 2):                        # one retry for a cold start or a rate-limit blip
        try:
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            return data, time.time() - t0, None, attempt
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(2)
    return {"reply": "", "steps": []}, 0.0, last, 2


# ------------------------------------------------------------------ scoring
def norm_time(v):
    """'2026-09-30', '2026-09-30 02:00', '2026-09-30T02:00:00Z' -> '2026-09-30 02:00'. None if not a date."""
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}):(\d{2}))?", str(v))
    return f"{m.group(1)} {m.group(2) or '00'}:{m.group(3) or '00'}" if m else None


def same(ref, got):
    t = norm_time(ref)
    if t:
        return t == norm_time(got)
    return str(ref).strip().lower() == str(got).strip().lower()


def to_dt(v):
    """'2026-09-13T11:30:01Z', '2026-09-13 11:30 UTC', '2026-09-30' -> datetime, or None if not a date."""
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?", str(v))
    return datetime(*(int(x or 0) for x in m.groups())) if m else None


def arg_ok(key, ref, got):
    """start/end: the agent's window may be tighter than the reference window, never wider or in another year.
    Everything else must match exactly (time strings are compared as minutes)."""
    if key in ("start", "end") and to_dt(ref) and to_dt(got):
        r, g = to_dt(ref), to_dt(got)
        return g >= r if key == "start" else g <= r
    return same(ref, got)


OPTIONAL_ARGS = {"level"}                # leaving a filter out gives a superset of the rows: not wrong


def call_matches(ref, steps):
    """True if some step called ref['tool'] with every reference argument (extra arguments are fine)."""
    for s in steps:
        if s["call"] != ref["tool"]:
            continue
        if all((k in s["args"] and arg_ok(k, v, s["args"][k])) or (k in OPTIONAL_ARGS and k not in s["args"])
               for k, v in ref["args"].items() if k not in SKIP_ARGS):
            return True
    return False


def args_diff(g, steps):
    """Plain text: for each reference call nobody matched, what was expected and what the agent actually sent."""
    out = []
    wanted = {t for alt in g["expected_tools"] for t in (alt if isinstance(alt, list) else [alt])}
    for r in g["reference_calls"]:
        if r["tool"] not in wanted or call_matches(r, steps):
            continue
        exp = {k: v for k, v in r["args"].items() if k not in SKIP_ARGS}
        got = [s["args"] for s in steps if s["call"] == r["tool"]]
        out.append(f"{r['tool']} expected {exp} | got {got if got else 'tool not called'}")
    return " ;; ".join(out)


def score(g, data):
    reply, steps = data.get("reply", ""), data.get("steps", [])
    called = {s["call"] for s in steps}
    used = {s["agent"] for s in steps}
    facts = all(has(reply, f) for f in g["must_include"])
    clean = not any(forbidden(reply, x) for x in g["must_not_include"])
    tools = all(any(t in called for t in (alt if isinstance(alt, list) else [alt])) for alt in g["expected_tools"])
    agents = all(a in used for a in g["expected_agents"])
    alts = [alt for alt in g["expected_tools"] if isinstance(alt, list)]
    def ok_call(r):          # an allowed alternative tool was used instead of this reference tool: not an args miss
        if call_matches(r, steps):
            return True
        return r["tool"] not in called and any(r["tool"] in alt and any(t in called for t in alt) for alt in alts)
    wanted = {t for alt in g["expected_tools"] for t in (alt if isinstance(alt, list) else [alt])}
    refs = [r for r in g["reference_calls"] if r["tool"] in wanted]      # extra reference calls are only for verify_golden
    args = all(ok_call(r) for r in refs)
    style = not NARRATION.search(reply)          # the hand-off rule: no "I will now transfer to..."
    return {"facts": facts, "clean": clean, "agents": agents, "tools": tools, "args": args, "style": style}


def auto_tags(c, error):
    """Which checks failed, in the order we read a trace: route first, then answer, then style."""
    if error:
        return ["error"]
    t = []
    if not c["agents"]:
        t.append("wrong_agent")
    if not c["tools"]:
        t.append("wrong_tool")
    elif not c["args"]:
        t.append("wrong_args")
    if not c["facts"]:
        t.append("missing_fact")
    if not c["clean"]:
        t.append("forbidden_content")
    if not c["style"]:
        t.append("narration")
    return t


def judge_row(g, data, err):
    """All derived fields for one trial. Used by the runner and by rescore.py so they can never disagree."""
    c = score(g, data)
    outcome = c["facts"] and c["clean"] and not err
    traj = c["agents"] and c["tools"] and c["args"] and not err
    strict = outcome and traj and c["style"]
    return {"checks": c, "outcome": outcome, "trajectory": traj, "strict": strict,
            "tags": [] if strict else auto_tags(c, err), "args_diff": "" if c["args"] else args_diff(g, data.get("steps", []))}


# ------------------------------------------------------------------ dataset helpers
def assign_splits(cases):
    """dev / heldout, stable and stratified: inside each category, every third case (by id) is held out.
    A 'split' field in the dataset wins if present. Tune prompts on dev; look at heldout rarely."""
    by = defaultdict(list)
    for g in cases:
        by[g["category"]].append(g)
    for rows in by.values():
        for i, g in enumerate(sorted(rows, key=lambda x: x["id"])):
            g.setdefault("split", "heldout" if i % 3 == 2 else "dev")
    return cases


def git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def file_hash(path):
    p = ROOT / path
    return hashlib.sha1(p.read_bytes()).hexdigest()[:8] if p.exists() else ""


def pct(n, d):
    return f"{100 * n / d:.0f}%" if d else "-"


# ------------------------------------------------------------------ main
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--name", default="", help="run name, becomes the folder eval/runs/<name>")
    p.add_argument("--dataset", default=str(ROOT / "eval" / "golden_v2.jsonl"))
    p.add_argument("--workers", type=int, default=3, help="parallel questions (watch Gemini rate limits)")
    p.add_argument("--trials", type=int, default=1, help="times to run each question (k)")
    p.add_argument("--split", default="all", choices=["all", "dev", "heldout"])
    p.add_argument("--category", default="")
    p.add_argument("--ids", default="", help="comma separated ids, e.g. G001,G002")
    a = p.parse_args()

    cases = assign_splits([json.loads(l) for l in open(a.dataset, encoding="utf-8")])
    if a.split != "all":
        cases = [c for c in cases if c["split"] == a.split]
    if a.category:
        cases = [c for c in cases if c["category"] == a.category]
    if a.ids:
        want = {x.strip() for x in a.ids.split(",")}
        cases = [c for c in cases if c["id"] in want]
    if not cases:
        raise SystemExit("no questions selected")

    run_id = a.name or time.strftime("run_%Y%m%d_%H%M%S")
    meta = {"run_id": run_id, "when": time.strftime("%Y-%m-%d %H:%M:%S"), "url": a.url, "trials": a.trials,
            "split": a.split, "dataset": Path(a.dataset).name, "git_sha": git_sha(),
            "agent_py_hash": file_hash("ops_agent/agent.py"), "grader": "v2", "questions": len(cases)}

    def run(job):
        g, trial = job
        data, secs, err, attempts = ask(a.url, g["question"])
        u = data.get("usage") or {}
        return {"run_id": run_id, "id": g["id"], "trial": trial, "category": g["category"], "difficulty": g["difficulty"],
                "split": g["split"], "question": g["question"], "expected": g["expected_answer"],
                "reply": data.get("reply", ""), "steps": data.get("steps", []), "model": data.get("model", ""),
                **judge_row(g, data, err),
                "seconds": round(secs, 2), "input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
                "model_calls": u.get("model_calls"), "attempts": attempts, "error": err}

    jobs = [(g, t) for g in cases for t in range(1, a.trials + 1)]
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        results = list(ex.map(run, jobs))
    wall = time.time() - t_start
    meta["wall_seconds"] = round(wall)
    meta["model"] = next((r["model"] for r in results if r["model"]), "")

    out = ROOT / "eval" / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "results.jsonl", "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- per question across trials: pass@k and pass^k
    per_q = defaultdict(list)
    for r in results:
        per_q[r["id"]].append(r)
    at_k = {"outcome": 0, "strict": 0}
    hat_k = {"outcome": 0, "strict": 0}
    for rs in per_q.values():
        for key in at_k:
            at_k[key] += any(x[key] for x in rs)
            hat_k[key] += all(x[key] for x in rs)

    # ---- table by category and by split
    def block(key_fn, title):
        groups = defaultdict(list)
        for r in results:
            groups[key_fn(r)].append(r)
        print(f"\n{title:<14}{'n':>4}{'outcome':>9}{'agents':>8}{'tools':>7}{'args':>6}{'strict':>8}{'avg s':>7}")
        rows = {}
        for k, rs in groups.items():
            n = len(rs)
            row = {"n": n, "outcome": sum(x["outcome"] for x in rs), "agents": sum(x["checks"]["agents"] for x in rs),
                   "tools": sum(x["checks"]["tools"] for x in rs), "args": sum(x["checks"]["args"] for x in rs),
                   "strict": sum(x["strict"] for x in rs), "avg_seconds": round(statistics.mean(x["seconds"] for x in rs), 1)}
            rows[k] = row
            print(f"{k:<14}{n:>4}{pct(row['outcome'], n):>9}{pct(row['agents'], n):>8}{pct(row['tools'], n):>7}"
                  f"{pct(row['args'], n):>6}{pct(row['strict'], n):>8}{row['avg_seconds']:>7}")
        return rows

    by_cat = block(lambda r: r["category"], "category")
    by_split = block(lambda r: r["split"], "split")

    n = len(results)
    secs = sorted(x["seconds"] for x in results)
    p50, p95 = statistics.median(secs), secs[min(n - 1, int(0.95 * n))]
    toks = [x["input_tokens"] + (x["output_tokens"] or 0) for x in results if x["input_tokens"] is not None]
    tag_counts = Counter(t for r in results if not r["strict"] for t in r["tags"][:1])   # first failing layer only
    nq = len(per_q)

    summary = {"meta": meta,
               "overall": {"trials_run": n, "outcome": sum(r["outcome"] for r in results), "strict": sum(r["strict"] for r in results),
                           "agents": sum(r["checks"]["agents"] for r in results), "tools": sum(r["checks"]["tools"] for r in results),
                           "args": sum(r["checks"]["args"] for r in results)},
               "reliability": {"questions": nq, "k": a.trials, "pass_at_k_outcome": at_k["outcome"], "pass_at_k_strict": at_k["strict"],
                               "pass_hat_k_outcome": hat_k["outcome"], "pass_hat_k_strict": hat_k["strict"]},
               "latency_seconds": {"p50": round(p50, 1), "p95": round(p95, 1), "mean": round(statistics.mean(secs), 1)},
               "tokens_per_question": round(statistics.mean(toks)) if toks else None,
               "model_calls_per_question": round(statistics.mean(x["model_calls"] for x in results if x["model_calls"]), 1)
               if any(x["model_calls"] for x in results) else None,
               "auto_failure_tags": dict(tag_counts), "by_category": by_cat, "by_split": by_split}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    with open(out / "failures.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "case_id", "trial", "category", "split", "question", "expected", "reply", "route_taken",
                    "auto_tag", "all_auto_tags", "args_diff", "human_tag", "first_failing_step", "note", "severity", "fix_idea"])
        for r in results:
            if r["strict"]:
                continue
            route = " > ".join(f"{s['agent']}:{s['call']}" for s in r["steps"])
            w.writerow([r["run_id"], r["id"], r["trial"], r["category"], r["split"], r["question"], r["expected"],
                        r["reply"][:600], route, (r["tags"] or ["unexplained"])[0], ";".join(r["tags"]), r["args_diff"], "", "", "", "", ""])

    print(f"\nrun {run_id}  |  {nq} questions x {a.trials} trial(s) = {n} runs  |  model {meta['model'] or '?'}  |  wall {wall:.0f}s")
    print(f"OUTCOME {pct(summary['overall']['outcome'], n)}   STRICT {pct(summary['overall']['strict'], n)}   "
          f"(strict = right answer AND right agents, tools and arguments)")
    if a.trials > 1:
        print(f"pass@{a.trials}: outcome {pct(at_k['outcome'], nq)}, strict {pct(at_k['strict'], nq)}   |   "
              f"pass^{a.trials}: outcome {pct(hat_k['outcome'], nq)}, strict {pct(hat_k['strict'], nq)}")
    print(f"latency p50 {p50:.1f}s, p95 {p95:.1f}s" + (f"   |   tokens per question ~{summary['tokens_per_question']}" if toks else
                                                           "   |   tokens: redeploy server.py to record them"))
    retried = sum(r["attempts"] > 1 for r in results)
    summary["overall"]["retried_requests"] = retried
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if retried:
        print(f"note: {retried} request(s) needed a retry (cold start, rate limit or error); they are counted by their final result")
    print(f"first failing layer: {dict(tag_counts) or 'none'}")
    print(f"saved: {out}  (results.jsonl, summary.json, failures.csv)")


if __name__ == "__main__":
    main()