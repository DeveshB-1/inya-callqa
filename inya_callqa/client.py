"""Thin read-only client for the Gnani Agent Builder Platform API
(https://docs.gnani.ai/Platform/platform-introduction).

Only GET-style operations plus prompt validation are exposed. Nothing here can
create, update or delete an agent, or place a phone call.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.inya.ai/platform"


class InyaError(RuntimeError):
    def __init__(self, status: int, message: str, request_id: str | None = None):
        self.status, self.request_id = status, request_id
        rid = f" (requestId {request_id})" if request_id else ""
        super().__init__(f"Inya API {status}: {message}{rid}")


class InyaClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        environment: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or os.environ.get("INYA_API_KEY")
        if not self.api_key:
            raise ValueError("Set INYA_API_KEY (Agent Builder > API keys) or pass api_key=")
        self.base_url = (base_url or os.environ.get("INYA_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        # Logs endpoint may 403 without ?environment= for some keys (per docs).
        self.environment = environment or os.environ.get("INYA_ENVIRONMENT") or "development"
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "InyaClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _call(self, method: str, path: str, **kw: Any) -> Any:
        r = self._http.request(method, path, **kw)
        try:
            body = r.json()
        except ValueError:
            raise InyaError(r.status_code, r.text[:200]) from None
        if r.status_code >= 400 or body.get("status") == "failure":
            raise InyaError(r.status_code, body.get("message", "unknown error"), body.get("requestId"))
        return body.get("response")

    @staticmethod
    def _page(page_no: int) -> int:
        # Docs: pageNo=0 returns HTTP 500 on List Agents and empty data on Logs.
        if page_no < 1:
            raise ValueError("page_no starts at 1")
        return page_no

    # ---- agents -------------------------------------------------------
    def list_agents(self, page_no: int = 1, page_size: int = 10, search: str | None = None) -> dict:
        params: dict[str, Any] = {"pageNo": self._page(page_no), "pageSize": page_size}
        if search:
            params["search"] = search
        return self._call("GET", "/v1/agents", params=params)

    def get_agent(self, bot_id: str) -> dict:
        return self._call("GET", f"/v1/agents/{bot_id}")

    def validate_prompt(self, system_prompt: str) -> dict:
        # Docs: an empty/missing systemPrompt silently returns isValidTemplate=true.
        if not system_prompt or not system_prompt.strip():
            raise ValueError("system_prompt is empty; the API would report it as valid")
        return self._call("POST", "/v1/agents/prompt/validate", json={"systemPrompt": system_prompt})

    # ---- conversations -----------------------------------------------
    def conversation_logs(
        self,
        page_no: int = 1,
        page_size: int = 10,
        bot_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        call_status: str | None = None,
        search_term: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {"environment": self.environment}
        if bot_id:
            params["botId"] = bot_id
        body: dict[str, Any] = {"pageNo": self._page(page_no), "pageSize": page_size}
        flt = {k: v for k, v in {"startDate": start_date, "endDate": end_date,
                                 "callStatus": call_status}.items() if v}
        if flt:
            body["filter"] = flt
        if search_term:
            body["searchTerm"] = search_term
        return self._call("POST", "/v1/conversations/logs", params=params, json=body)

    def conversation_stats(self, conversation_id: str) -> dict:
        resp = self._call("GET", f"/v1/conversations/{conversation_id}/stats")
        # Documented shape: response is a one-element list.
        if isinstance(resp, list):
            if not resp:
                raise InyaError(404, f"no stats for conversation {conversation_id}")
            return resp[0]
        return resp

    def recent_calls(self, limit: int = 20, **log_filters: Any) -> list[dict]:
        """Page through Logs, then fetch Stats (full transcript) for each call."""
        ids: list[str] = []
        page = 1
        while len(ids) < limit:
            data = self.conversation_logs(page_no=page, page_size=min(100, limit), **log_filters)
            rows = data.get("data") or []
            ids += [r["conversationId"] for r in rows if r.get("conversationId")]
            if not rows or page >= (data.get("totalPages") or 1):
                break
            page += 1
        return [self.conversation_stats(cid) for cid in ids[:limit]]
