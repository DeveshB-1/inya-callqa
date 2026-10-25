import json

import anyio
import pytest
from conftest import ROOT
from mcp import Client

from inya_callqa import server
from inya_callqa.client import InyaClient

WRITE_VERBS = ("create", "update", "delete", "trigger", "import", "upload")


@pytest.fixture
def wired(mock_api, monkeypatch):
    monkeypatch.setattr(server, "_client", InyaClient(api_key="demo", base_url=mock_api))
    yield
    server._client = None


def _data(res):
    assert not res.is_error, res.content
    return res.structured_content or json.loads(res.content[0].text)


def test_tools_are_read_only():
    async def go():
        async with Client(server.mcp) as c:
            return [t.name for t in (await c.list_tools()).tools]
    names = anyio.run(go)
    assert {"list_agents", "audit_recent_calls", "audit_transcript", "get_conversation"} <= set(names)
    assert not [n for n in names if n.startswith(WRITE_VERBS)]


def test_audit_transcript_needs_no_key(monkeypatch):
    monkeypatch.delenv("INYA_API_KEY", raising=False)
    payload = (ROOT / "fixtures" / "docs_example_stats.json").read_text(encoding="utf-8")

    async def go():
        async with Client(server.mcp) as c:
            return _data(await c.call_tool("audit_transcript", {"stats_json": payload}))
    data = anyio.run(go)
    assert data["rollup"]["calls_with_high_severity"] == 1


def test_audit_recent_calls_over_http(wired):
    async def go():
        async with Client(server.mcp) as c:
            return _data(await c.call_tool("audit_recent_calls", {"limit": 10}))
    data = anyio.run(go)
    assert data["rollup"]["calls"] == 4
    assert {c["conversation_id"] for c in data["calls"]} == {"1786433682702486082", "syn-hi-001", "syn-kn-001"}


def test_audit_conversation_by_id(wired):
    async def go():
        async with Client(server.mcp) as c:
            return _data(await c.call_tool("audit_conversation", {"conversation_id": "syn-kn-001"}))
    data = anyio.run(go)
    assert data["findings_by_severity"] == {"medium": 3}
