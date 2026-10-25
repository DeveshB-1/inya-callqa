"""MCP server: lets Claude Code / Claude Desktop / Cursor read Inya agents and
calls and run the code-mixed call audit. Read-only by design: no tool can
create, edit or delete an agent, or trigger an outbound call.

Run:  INYA_API_KEY=... inya-callqa serve
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from .audit import audit_call, calls_from_payload, rollup
from .client import InyaClient

mcp = MCPServer(
    name="inya-callqa",
    instructions=(
        "Read-only access to Gnani Inya voice agents. Use audit_recent_calls to find "
        "calls where the agent spoke unrendered template variables, answered in the wrong "
        "language, ignored a question, or where the parallel ASR hypotheses disagree. "
        "audit_transcript works offline on pasted Stats JSON and needs no API key."
    ),
)

_client: InyaClient | None = None


def client() -> InyaClient:
    global _client
    if _client is None:
        _client = InyaClient()
    return _client


@mcp.tool()
def list_agents(search: str = "", page_no: int = 1, page_size: int = 10) -> dict[str, Any]:
    """List voice agents in the organisation (botId, name, languages)."""
    return client().list_agents(page_no=page_no, page_size=page_size, search=search or None)


@mcp.tool()
def get_agent(bot_id: str) -> dict[str, Any]:
    """Full configuration for one agent: prompt, ASR/TTS, languages, webhook."""
    return client().get_agent(bot_id)


@mcp.tool()
def list_conversations(
    bot_id: str = "",
    start_date: str = "",
    end_date: str = "",
    call_status: str = "",
    page_no: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """List past calls (conversationId, bot, start/end). Dates are ISO 8601."""
    return client().conversation_logs(
        page_no=page_no, page_size=page_size, bot_id=bot_id or None,
        start_date=start_date or None, end_date=end_date or None, call_status=call_status or None,
    )


@mcp.tool()
def get_conversation(conversation_id: str) -> dict[str, Any]:
    """Outcome, disposition and full turn-by-turn transcript for one call."""
    return client().conversation_stats(conversation_id)


@mcp.tool()
def audit_conversation(conversation_id: str, disagreement_threshold: float = 0.75) -> dict[str, Any]:
    """Fetch one call and run the QA checks on it."""
    call = client().conversation_stats(conversation_id)
    return audit_call(call, disagreement_threshold=disagreement_threshold).to_dict()


@mcp.tool()
def audit_recent_calls(
    bot_id: str = "",
    limit: int = 20,
    start_date: str = "",
    end_date: str = "",
    disagreement_threshold: float = 0.75,
) -> dict[str, Any]:
    """Audit the most recent calls of an agent and return a rollup plus per-call findings."""
    calls = client().recent_calls(
        limit=limit, bot_id=bot_id or None, start_date=start_date or None, end_date=end_date or None,
        call_status="ANSWERED",
    )
    reports = [audit_call(c, disagreement_threshold=disagreement_threshold) for c in calls]
    return {"rollup": rollup(reports), "calls": [r.to_dict() for r in reports if r.findings]}


@mcp.tool()
def audit_transcript(stats_json: str, disagreement_threshold: float = 0.75) -> dict[str, Any]:
    """Audit a pasted Stats API response (or post-call webhook converted to the same
    shape). Works without an API key."""
    calls = calls_from_payload(json.loads(stats_json))
    reports = [audit_call(c, disagreement_threshold=disagreement_threshold) for c in calls]
    return {"rollup": rollup(reports), "calls": [r.to_dict() for r in reports]}


@mcp.tool()
def validate_prompt(system_prompt: str) -> dict[str, Any]:
    """Check a Jinja2 system prompt and list the variables it expects at call time."""
    return client().validate_prompt(system_prompt)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
