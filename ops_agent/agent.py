"""Overwatch-mini: a root agent that delegates to two specialist agents.

   ops_assistant (root)
     |-- incidents_agent --MCP--> itsm_server.py --> Supabase itsm.incidents
     |-- logs_agent      --MCP--> logs_server.py  --> Supabase logs.entries
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")   # one .env in the project root serves adk web and the server

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
SERVERS = ROOT / "mcp_servers"


def mcp_server(script: str) -> McpToolset:
    """Start one MCP server as a child process and expose its tools to an agent."""
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=[str(SERVERS / script)],
                env=dict(os.environ),          # passes DATABASE_URL to the server
            ),
            timeout=30,
        )
    )


incidents_agent = Agent(
    name="incidents_agent",
    model=MODEL,
    description="Looks up IT incidents (tickets): priority, service, status, summary.",
    instruction=("Answer using the incident tools only. Quote incident IDs, priority "
                 "and status exactly as returned. Always include the priority, service, status, summary and opened time.If nothing is found, say so."),
    tools=[mcp_server("itsm_server.py")],
)

logs_agent = Agent(
    name="logs_agent",
    model=MODEL,
    description="Searches application logs for a service (payments, checkout, search).",
    instruction=("Answer using the log tool only. Quote timestamps and messages exactly "
                 "as returned. If there are no matching logs, say so."),
    tools=[mcp_server("logs_server.py")],
)

root_agent = Agent(
    name="ops_assistant",
    model=MODEL,
    description="IT operations assistant.",
    instruction=(
        "You are an IT operations assistant. Never answer from memory. "
        "For incident or ticket questions, delegate to incidents_agent. "
        "For log or error questions, delegate to logs_agent. "
        "If a question needs both, use both, then combine the results. "
        "Only state facts the specialists returned; if they found nothing, say so. "
        "Be concise."
    ),
    sub_agents=[incidents_agent, logs_agent],
)
