# Overwatch Mini

A small practice copy of Costco's Overwatch idea: an AI assistant for IT operations. You ask a question in a chat page, a team of AI agents looks in three mock systems (incidents, logs, metrics), and you see which agent called which tool.

```
chat page (docs/, GitHub Pages) --HTTPS--> backend (server.py, Cloud Run)
                                              ops_assistant (root agent, Google ADK + Gemini)
                                               |- incidents_agent --MCP--> itsm_server.py          (3 tools) ---\
                                               |- logs_agent      --MCP--> observability_server.py (3 tools) ----+--> Supabase Postgres
                                               '- metrics_agent   --MCP--> observability_server.py (2 tools) ---/    schemas: itsm, logs, metrics
```

- **Agents** (`ops_agent/agent.py`): a root agent that sends each question to a specialist. A specialist can hand over to the next one (incidents, then logs, then metrics), so one question can use all three.
- **MCP servers** (`mcp_servers/`): two small Python programs that give the agents their tools. The SQL is fixed inside each tool; the model never writes SQL. `observability_server.py` has 5 tools, and each agent is given only its own with `tool_filter`.
- **Database**: Supabase Postgres with about 59,000 made-up rows for September 2026 (see `supabase/DATA_V2.md`).
- **Chat page** (`docs/index.html`): plain HTML. GitHub Pages only serves static files, so the agents run in the backend and the page just calls `/chat`.

## Run it on your own machine

You need: Python 3.11 or newer, git, a free [Supabase](https://supabase.com) account, and a way to call Gemini (a Google Cloud project with Vertex AI and the `gcloud` CLI, or a free Gemini API key; see `.env.example`).

**1. Get the code and install**

```powershell
git clone https://github.com/jagadeepavula/demowatch_mini.git
cd demowatch_mini
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
On macOS or Linux, activate with `source .venv/bin/activate` instead. If PowerShell refuses to activate, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

**2. Make your own database**

1. In Supabase: New project (free plan). Save the database password.
2. Click **Connect** at the top, then **Session pooler**, and copy the connection string. Put your password in place of `[YOUR-PASSWORD]`.
   Use the **Session pooler** string, not "Direct connection": Direct is IPv6 only and fails on many networks and on Cloud Run.

**3. Fill in `.env`**

```powershell
copy .env.example .env
```
Open `.env` and set `DATABASE_URL` and your Gemini settings (`GOOGLE_CLOUD_PROJECT`, or `GOOGLE_API_KEY` for the key route).

**4. Load the data and check it**

```powershell
python data_gen/load_db.py      # type yes; it takes about 1 to 2 minutes
python data_gen/check_v2.py     # should end with ALL CHECKS PASSED
```
This creates the tables in your own Supabase project, and replaces any tables of the same names there. To look at them: Supabase **Table Editor**, then switch the schema dropdown from `public` to `itsm`, `logs`, `metrics` or `evalmeta`.

**5. Log in to Google (Vertex route only)**

```powershell
gcloud auth application-default login
gcloud services enable aiplatform.googleapis.com
```

**6. Run it**

```powershell
adk web                          # the ADK dev screen: pick ops_agent and see every step
uvicorn server:app --port 8080   # the real backend; open http://localhost:8080 for the chat page
```
Run both commands from the project folder (the one with `server.py`).

Questions to try:
- Is INC0428 still open?  (incidents agent)
- How many ERROR logs did notifications write on 20 September 2026?  (logs agent)
- What was the payments error rate from 02:00 to 05:00 UTC on 30 September 2026?  (metrics agent)
- What is the status of INC0428, and what do the payments logs and metrics show from 01:00 UTC on 30 September 2026?  (all three agents)

All data is from **1 to 30 September 2026, in UTC**. Say the dates in your question.

## One database for everyone, or one each?
Each person making their own free Supabase project (step 2) is the simplest, and nobody can break anyone else's data. The agents only read, but `load_db.py` replaces tables, so do not point it at a shared database by accident.

## Deploying (done once, by whoever owns the Google Cloud project)
The live backend is a Cloud Run service and the page is served from the `docs/` folder by GitHub Pages. Peers do not need to deploy anything.

First time (bash; use Cloud Shell or Git Bash on Windows):
```bash
export PROJECT=<your-gcp-project-id>
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com aiplatform.googleapis.com
printf '%s' "$DATABASE_URL" | gcloud secrets create db-url --data-file=-
SA=$(gcloud projects describe $PROJECT --format='value(projectNumber)')-compute@developer.gserviceaccount.com
gcloud secrets add-iam-policy-binding db-url --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=roles/aiplatform.user
gcloud run deploy demowatch-mini --source . --region us-central1 --allow-unauthenticated --max-instances 2 --memory 1Gi --timeout 300 \
  --set-secrets DATABASE_URL=db-url:latest \
  --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=us-central1,ALLOWED_ORIGINS=https://<github-user>.github.io
```
Put the service URL it prints into `docs/config.js` (`window.API_URL`), then commit and push. In GitHub: Settings, Pages, Source "Deploy from a branch", `main` and `/docs`.

Every later change:
```powershell
gcloud run deploy demowatch-mini --source . --region us-central1 --memory 1Gi --timeout 300   # backend
git add . ; git commit -m "message" ; git push                                                  # page (Pages updates in about a minute)
```
The earlier settings (secret, variables, public access) are kept, so you do not repeat them.

The backend URL is public, so anyone with it spends your Gemini credit. `--max-instances 2` and `ALLOWED_ORIGINS` limit this. Set a billing alert too. Sessions live in memory, so a new instance forgets the conversation.

## What is where
| Path | What it is |
|---|---|
| `ops_agent/agent.py` | the root agent and the three specialists, and how each gets its tools |
| `mcp_servers/` | `itsm_server.py` (3 tools), `observability_server.py` (5 tools), `db.py` (the only database code) |
| `server.py` | the `/chat` API around the agents; it also serves `docs/` |
| `docs/` | the chat page and `config.js` (where the page sends questions) |
| `supabase/schema_v2.sql`, `data_gen/` | the database tables and the generator that fills them; `supabase/DATA_V2.md` describes every table, scenario and awkward row |
| `eval/`, `data_gen/make_golden_v2.py` | a starting point for evals (see below) |

## Not done yet
Evaluation and observability come next, as a team. `eval/` and `data_gen/make_golden_v2.py` are a first draft: 64 golden questions whose answers are read from the database. `python eval/verify_golden.py` checks that the tools agree with the database, and `python eval/run_eval.py --url <backend>` asks the live chatbot. Also still to do: CI/CD, gate tests, and a tool to read deployment changes (right now the agents say they do not have that).

## If something breaks
| Symptom | Fix |
|---|---|
| `Network is unreachable` or a timeout connecting to the database | You used the Direct string. Use the **Session pooler** string. |
| `No module named 'mcp.server.fastmcp'` | You have mcp 2.x. Run `pip install "mcp<2"` (requirements.txt already pins it). |
| `Could not import module "server"` | You are in the wrong folder. `cd` into the one that contains `server.py`. |
| Model not found, or 403 / permission error from Vertex | Check `GOOGLE_CLOUD_PROJECT`, run the two `gcloud` commands in step 5, or set `GEMINI_MODEL` to a model your project can use. |
| Page says "Could not reach the backend" | Check `window.API_URL` in `docs/config.js`. On Cloud Run, `ALLOWED_ORIGINS` must match your Pages address exactly, with no trailing slash. |
| Cloud Run says the container failed to start | Read the revision's log (the link in the error). Do not list `docs/` in `.dockerignore`. |
| The agent answers without calling tools | Open it in `adk web` and read the steps; tighten the `instruction` in `ops_agent/agent.py`. |
| Everything was fine, now the database refuses | Supabase free projects pause after about a week idle. Click Restore in the dashboard. |