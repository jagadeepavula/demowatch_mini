"""Backend for the chat page. One endpoint: POST /chat.

GitHub Pages can only host static files, so the agent runs here (Cloud Run)
and the page on GitHub Pages calls this API.
"""
import os
from dotenv import load_dotenv
load_dotenv()

import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

from ops_agent.agent import root_agent

APP = "overwatch_mini"
sessions = InMemorySessionService()
runner = Runner(agent=root_agent, app_name=APP, session_service=sessions)

app = FastAPI(title="Overwatch Mini")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/chat")
async def chat(body: ChatIn):
    sid = body.session_id or uuid.uuid4().hex
    if not await sessions.get_session(app_name=APP, user_id="web", session_id=sid):
        await sessions.create_session(app_name=APP, user_id="web", session_id=sid)

    texts, steps = [], []
    msg = types.Content(role="user", parts=[types.Part(text=body.message)])
    async for ev in runner.run_async(user_id="web", session_id=sid, new_message=msg):
        for p in (ev.content.parts if ev.content and ev.content.parts else []):
            if p.function_call:
                steps.append({"agent": ev.author, "call": p.function_call.name,
                              "args": dict(p.function_call.args or {})})
        # Keep the text of every agent in the chain (an agent writes its part, then hands over to the next one).
        if ev.content and ev.content.parts and ev.author != "user" and not ev.partial:
            t = "".join(p.text or "" for p in ev.content.parts if p.text and not p.thought).strip()
            if t:
                texts.append(t)
    reply = "\n\n".join(texts)
    return {"session_id": sid, "reply": reply or "(no answer)", "steps": steps}


# Serve the chat page from the same server (http://localhost:8080). Must stay LAST so /chat and /health win.
# Skipped when the docs folder is not in the container (the page can live on GitHub Pages only).
_docs = os.path.join(os.path.dirname(__file__), "docs")
if os.path.isdir(_docs):
    app.mount("/", StaticFiles(directory=_docs, html=True), name="ui")