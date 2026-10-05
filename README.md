# Overwatch Mini

```
GitHub Pages chat (docs/)  --HTTPS-->  Cloud Run backend (server.py)
                                          ops_assistant (root agent, Google ADK + Gemini)
                                           |- incidents_agent --MCP--> itsm_server.py (3 tools) ----------\
                                           |- logs_agent      --MCP--> observability_server.py (3 tools) --+--> Supabase Postgres
                                           '- metrics_agent   --MCP--> observability_server.py (2 tools) --/    (itsm, logs, metrics)
```
The observability server is one file with 5 tools; each agent gets only its own tools through `tool_filter` in `ops_agent/agent.py`.
GitHub Pages only serves static files, so the agent cannot run there. The page is just the chat window. The agent runs on Cloud Run (uses your GCP credit) and reads data from Supabase.

You need: Supabase account, GitHub account, your GCP project, Python 3.11+, `gcloud` CLI.

---
## Step 1. Create the database in Supabase
1. supabase.com -> New project (free plan). Save the database password.
2. Click **Connect** (top bar) -> **Session pooler** -> copy the connection string. Replace `[YOUR-PASSWORD]`.
   Use the pooler string, not "Direct connection". Direct is IPv6 only and Cloud Run cannot reach it.

3. Put the string in `.env` as `DATABASE_URL` (Step 2), then load the data: `python data_gen/load_db.py` (type `yes`) and check it with `python data_gen/check_v2.py`.
4. Table Editor: switch the schema dropdown to `itsm`, `logs`, `metrics` and `evalmeta` to see the rows.

Four schemas stand in for the systems: `itsm` = mock ServiceNow, `logs` = mock Splunk, `metrics` = mock Dynatrace, `evalmeta` = answers for the evals (agents never read it).

## Step 2. Run it on your machine
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # fill in GOOGLE_CLOUD_PROJECT and DATABASE_URL
gcloud auth application-default login
gcloud services enable aiplatform.googleapis.com
adk web                         # open the link, pick ops_agent, ask a question
```
`adk web` shows every tool call and which agent made it. Use it to learn how delegation works.

Then the real backend plus the page:
```bash
uvicorn server:app --port 8080
# open docs/index.html in your browser (config.js already points at localhost:8080)
```
Questions to try:
- Is INC0428 still open?  (incidents agent)
- How many ERROR logs did notifications write on 20 September 2026?  (logs agent)
- What was the payments error rate from 02:00 to 05:00 UTC on 30 September 2026?  (metrics agent)
- What is the status of INC0428, and what do the payments logs and metrics show from 01:00 UTC on 30 September 2026?  (all three agents)

## Step 3. Put the code on GitHub and publish the page
```bash
git init && git add . && git commit -m "Overwatch mini"
git branch -M main
git remote add origin https://github.com/<you>/overwatch-mini.git
git push -u origin main
```
On GitHub: repo -> Settings -> Pages -> Source: **Deploy from a branch** -> `main` / `/docs` -> Save.
Your page appears at `https://<you>.github.io/overwatch-mini/` in a minute or two.
`.env` is in `.gitignore`. Never commit it.

## Step 4. Deploy the backend to Cloud Run
```bash
export PROJECT=<your-gcp-project-id>
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

# keep the DB password in Secret Manager, not in the command
printf '%s' "$DATABASE_URL" | gcloud secrets create db-url --data-file=-
SA=$(gcloud projects describe $PROJECT --format='value(projectNumber)')-compute@developer.gserviceaccount.com
gcloud secrets add-iam-policy-binding db-url --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/aiplatform.user

gcloud run deploy overwatch-mini --source . --region us-central1 \
  --allow-unauthenticated --max-instances 2 --memory 1Gi --timeout 300 \
  --set-secrets DATABASE_URL=db-url:latest \
  --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=us-central1,ALLOWED_ORIGINS=https://<you>.github.io
```
Copy the service URL it prints, then:
1. Put it in `docs/config.js` as `window.API_URL`.
2. `git add docs/config.js && git commit -m "point UI at backend" && git push`
3. Open your GitHub Pages address and ask a question.

## Cost and safety
- The backend URL is public, so anyone with it can spend your Gemini credit. `--max-instances 2` and `ALLOWED_ORIGINS` limit this. Also set a budget alert (Billing -> Budgets) at about $20.
- Supabase free projects pause after about a week with no activity. Click Restore in the dashboard if that happens.
- Sessions are held in memory, so a new Cloud Run instance forgets the conversation. Fine for learning.

## If something breaks
| Symptom | Fix |
|---|---|
| `connection ... Network is unreachable` | You used the Direct string. Use the Session pooler string. |
| Model not found | Set `GEMINI_MODEL` in `.env` to a model your project can use. |
| Page says "Could not reach the backend" | Check `API_URL`; on Cloud Run check `ALLOWED_ORIGINS` matches your Pages address exactly (no trailing slash). |
| Agent answers without calling tools | Look in `adk web`; tighten the agent `instruction` in `ops_agent/agent.py`. |
| 403 from Vertex on Cloud Run | The Cloud Run service account needs `roles/aiplatform.user` (done above). |

## What is where
- `supabase/schema.sql` tables and sample rows
- `mcp_servers/` two MCP servers: `itsm_server.py` and `observability_server.py`. Each `@mcp.tool()` function becomes a tool.
- `ops_agent/agent.py` root agent and three specialists. `McpToolset` starts a server and hands its tools to the agent.
- `server.py` the `/chat` API around the agent
- `docs/` the GitHub Pages chat page

## Database version 2 (use this one for evals)
A bigger, harder database: itsm + logs + metrics + a hidden `evalmeta` schema with ground truth. About 59,000 rows, 15 planted scenarios, 19 awkward rows.
```powershell
python data_gen/load_db.py     # replaces the v1 tables on your DATABASE_URL (Session pooler string)
python data_gen/check_v2.py    # plain-SQL checks, no AI model
```
Read `supabase/DATA_V2.md` for every table, scenario and edge case. The two sections below describe version 1; `seed_large.sql`, `generate.py` and the current golden set do not match version 2 and need regenerating.

### Golden questions for version 2
```powershell
python data_gen/make_golden_v2.py      # writes eval/golden_v2.jsonl (64 questions, answers read from the database)
python eval/verify_golden.py           # tools and SQL must agree (no AI model)
python eval/run_eval.py --url https://YOUR-SERVICE.run.app --workers 3
```
Categories: lookup, aggregation, log_count, log_search, metrics, problems, cross_source, out_of_scope, negative, safety.

## Version 1 bigger database and golden dataset (old)
- `supabase/seed_large.sql` replaces the small tables with 60 incidents and about 1,100 log lines across 8 services (SQL Editor -> paste -> Run; choose "Run and enable RLS" if asked).
- `data_gen/generate.py` rebuilds that file and the golden set. It is seeded, so the output never changes unless you change the script.
- `eval/golden_dataset.jsonl` holds 49 questions in 7 categories. The expected answers are computed from the data, not written by hand.
- `python eval/verify_golden.py` checks every golden answer against the real database with no AI model involved. Run it after any data change.
- `python eval/run_eval.py --url https://YOUR-SERVICE.run.app --workers 3` asks the live chatbot every question and prints pass rates by category, plus time per question.
- New MCP tools make the questions answerable: `count_incidents`, `count_logs`, `error_counts_by_service`, and date, priority and level filters.

After changing the tools, `requirements.txt` or the agents, redeploy with `gcloud run deploy demowatch-mini --source . --region us-central1`.

Later: Neo4j knowledge agent, LLM-as-judge scoring, OpenTelemetry traces and dashboards.
