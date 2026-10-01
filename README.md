# demowatch_mini

```
GitHub Pages chat (docs/)  --HTTPS-->  Cloud Run backend (server.py)
                                          ops_assistant (root agent, Google ADK + Gemini)
                                           |- incidents_agent --MCP--> itsm_server.py --\
                                           '- logs_agent      --MCP--> logs_server.py  ---> Supabase Postgres
                                                                                         (schemas: itsm, logs)
```
GitHub Pages only serves static files, so the agent cannot run there. The page is just the chat window. The agent runs on Cloud Run (uses your GCP credit) and reads data from Supabase.

You need: Supabase account, GitHub account, your GCP project, Python 3.11+, `gcloud` CLI.

---
## Step 1. Create the database in Supabase
1. supabase.com -> New project (free plan). Save the database password.
2. SQL Editor -> New query -> paste all of `supabase/schema.sql` -> Run.
3. Table Editor: switch the schema dropdown to `itsm` and `logs` and check the rows are there.
4. Click **Connect** (top bar) -> **Session pooler** -> copy the connection string. Replace `[YOUR-PASSWORD]`.
   Use the pooler string, not "Direct connection". Direct is IPv6 only and Cloud Run cannot reach it.

Two schemas in one project stand in for two systems: `itsm` = mock ServiceNow, `logs` = mock Splunk.

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
- Is INC0428 still open?
- Show error logs for payments
- Which incidents are open, and do those services have errors in the logs?  (uses both agents)

## Step 3. Put the code on GitHub and publish the page
```bash
git init && git add . && git commit -m "demowatch_mini"
git branch -M main
git remote add origin https://github.com/<you>/demowatch_mini.git
git push -u origin main
```
On GitHub: repo -> Settings -> Pages -> Source: **Deploy from a branch** -> `main` / `/docs` -> Save.
Your page appears at `https://<you>.github.io/demowatch_mini/` in a minute or two.
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

# Cloud Run service names use hyphens rather than underscores.
gcloud run deploy demowatch-mini --source . --region us-central1 \
  --allow-unauthenticated --max-instances 2 \
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
- `mcp_servers/` one MCP server per system. Each `@mcp.tool()` function becomes a tool.
- `ops_agent/agent.py` root agent and two specialists. `McpToolset` starts a server and hands its tools to the agent.
- `server.py` the `/chat` API around the agent
- `docs/` the GitHub Pages chat page

Later: Neo4j knowledge agent, evaluation, observability.
