.# Evals: how we test the assistant

This folder is how we measure whether the agents answer correctly. Start here if you are new to evals.

## The idea in one minute

Think of an exam. `golden_v2.jsonl` is the exam paper (64 questions with known correct answers). The chatbot on Cloud Run is the student. `run_eval.py` is the marker. Marking never calls Gemini or the database itself: it only sends each question to the backend, reads back the reply and the list of steps (which agent called which tool with which inputs), and checks them.

## What each file does

| File | What it is |
|---|---|
| `golden_v2.jsonl` | The 64 test questions. Each has the expected facts, expected agent and tool, and the reference tool call. **Generated** by `data_gen/make_golden_v2.py` from SQL, so edit that script, not this file |
| `verify_golden.py` | Checks the golden answers against the real database with no AI model (tool unit tests) |
| `run_eval.py` | Runs every question against the live backend, marks it, and saves a run folder |
| `common.py` | The matching rules (`has` for required facts, `forbidden` for banned phrases) |
| `rescore.py` | Re-marks a saved run with the current rules. No Gemini calls. Writes `failure_detail.txt` |
| `compare_runs.py` | Before and after: which questions got fixed, which broke |
| `runs/<name>/` | Saved runs: `results.jsonl`, `summary.json`, `failures.csv` |

## How a question is marked

| Check | Passes if |
|---|---|
| facts | every required fact appears in the reply |
| clean | no forbidden phrase appears (negated phrases like "not every incident is resolved" are fine) |
| agents | the expected specialist agent was used |
| tools | the expected tool was called |
| args | the tool was called with the reference arguments (time formats are normalised) |
| style | no hand-off narration such as "I will now transfer to..." |

- **outcome** = facts and clean. Was the answer right?
- **trajectory** = agents and tools and args. Was the route right?
- **strict** = outcome and trajectory and style. This is the number we track.
- **pass@k / pass^k** (with `--trials k`): at least one trial passed, versus every trial passed.

## Run it

Run from the folder that contains `server.py`. You need the team `.env` and the backend URL.

```powershell
# no AI model, checks the answers against the database
python eval/verify_golden.py

# a quick smoke test on three questions
python eval/run_eval.py --url <BACKEND_URL> --name smoke --ids G001,G030,G048 --workers 2

# the full set (about 3 to 4 minutes)
python eval/run_eval.py --url <BACKEND_URL> --name my_run --workers 2

# re-mark a saved run after changing the rules (no Gemini calls)
python eval/rescore.py baseline

# compare two runs
python eval/compare_runs.py baseline my_run
```

Useful flags: `--split dev` or `--split heldout`, `--category lookup`, `--trials 3`.

## Rules for working here

1. **Tune on the dev split.** Every third case in each category is held out. Look at `--split heldout` only to report, not to decide what to change.
2. **Never overwrite `runs/baseline/`.** Give your own runs your own names.
3. **Change the answer key through a pull request.** Say which case and why, so a second person can check.
4. **Before blaming the agent, check the key and the grader.** In our first baseline 15 of 26 failures were answer-key or grader problems, not agent problems.
5. **Do not paste `.env` values** into runs, notes or chat.

## Where we are

Done:
- 64 golden questions with ground truth computed from SQL, all verified against the database.
- A harness that marks outcome, routing, tools, arguments and style separately.
- A first baseline run (`runs/baseline/`), one trial per question. As first marked: 75% outcome, 59% strict (38/64).
- We then checked the failures before blaming the agent. 15 of the first 26 were answer-key or grader problems (a trailing-space bug, negation, too-strict routes for refusals, one-second time windows). Re-marked with the fixed key: 56/64 outcome (88%), 53/64 strict (83%). Same saved replies, no new Gemini calls.
- 11 failures left: 7 real agent problems (looping on counts, wrong year, no tool call, narration "I will now transfer..."), 2 tool gaps (oldest-first list, child incidents), 1 judgement call (G059, quoting an injected line), and G062 (searched a one-second window and found nothing).

Next:
1. Re-score the baseline with the fixed grader (`rescore.py baseline`) and confirm the failure groups.
2. Review the 64 cases with a domain expert: expected answer, expected route, rubric.
3. Fix the real agent failures and tool gaps, re-run, and compare with `compare_runs.py`.
4. Run several trials per case and report pass^k.
5. Agree a release rule (for example: no drop in strict score or in any category).
6. Add one narrow, calibrated model judge for what code rules cannot check.

## How to pick this up

Pick one track:

- **Track A, read the failures.** Open `runs/baseline/failures.csv`, read the `reply` and `route_taken` for each row, and fill `human_tag`, `note` and `fix_idea`. This is error analysis.
- **Track B, review the answer key.** Take one category in `golden_v2.jsonl`. For each case ask: is the question clear, is the expected answer right, are the expected agent and tool the only valid route? Propose changes in `data_gen/make_golden_v2.py`.
- **Track C, fix the agent.** Pick a real failure from track A, change the instruction in `ops_agent/agent.py` or a tool in `mcp_servers/`, then re-run and compare.

Suggested reading, in order: Hamel Husain's "Your AI Product Needs Evals" and his LLM Evals FAQ, ADK's "Evaluate agents" page, then the Golden Datasets document the team shares.