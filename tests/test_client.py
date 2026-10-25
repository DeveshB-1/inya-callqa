import httpx
import pytest

from inya_callqa.client import InyaClient, InyaError


def test_requires_key(monkeypatch):
    monkeypatch.delenv("INYA_API_KEY", raising=False)
    with pytest.raises(ValueError):
        InyaClient()


def test_sends_documented_request_shape():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers["x-api-key"], req.content
        return httpx.Response(200, json={"status": "success", "requestId": "r1",
                                         "response": {"pageNo": 1, "totalPages": 1, "data": []}})

    c = InyaClient(api_key="k", base_url="https://api.inya.ai/platform", transport=httpx.MockTransport(handler))
    c.conversation_logs(bot_id="b1", start_date="2026-10-01T00:00:00Z", call_status="ANSWERED")
    assert seen["url"] == "https://api.inya.ai/platform/v1/conversations/logs?environment=development&botId=b1"
    assert seen["key"] == "k"
    assert b'"filter":{"startDate":"2026-10-01T00:00:00Z","callStatus":"ANSWERED"}' in seen["body"].replace(b" ", b"")


def test_error_carries_request_id():
    t = httpx.MockTransport(lambda r: httpx.Response(
        403, json={"status": "failure", "requestId": "abc", "message": "User does not have access to this conversation"}))
    c = InyaClient(api_key="k", transport=t)
    with pytest.raises(InyaError) as e:
        c.conversation_stats("123")
    assert e.value.status == 403 and e.value.request_id == "abc" and "abc" in str(e.value)


def test_guards_documented_footguns():
    c = InyaClient(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(ValueError):
        c.list_agents(page_no=0)  # docs: pageNo=0 -> HTTP 500
    with pytest.raises(ValueError):
        c.validate_prompt("  ")  # docs: empty prompt silently "valid"


def test_recent_calls_against_mock_server(mock_api):
    with InyaClient(api_key="demo", base_url=mock_api) as c:
        calls = c.recent_calls(limit=3)
        assert len(calls) == 3
        assert all("utteranceAnalytics" in x for x in calls)
        assert c.list_agents()["totalCount"] == 3
        assert c.validate_prompt("Hi {{ customer_name }}, due {{ due_amount }}")["variables"] == ["customer_name", "due_amount"]


def test_pagination_walks_pages(mock_api):
    with InyaClient(api_key="demo", base_url=mock_api) as c:
        page1 = c.conversation_logs(page_no=1, page_size=2)
        assert page1["totalPages"] == 2
        assert len(c.recent_calls(limit=10)) == 4


def test_bad_key_against_mock_server(mock_api):
    with InyaClient(api_key="wrong", base_url=mock_api) as c, pytest.raises(InyaError) as e:
        c.list_agents()
    assert e.value.status == 401
