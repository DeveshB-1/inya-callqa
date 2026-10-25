"""Local stand-in for https://api.inya.ai/platform, serving the fixtures in the
documented response envelopes. Used only for the demo; no Gnani key needed.

    python scripts/mock_inya.py 18431
    INYA_API_KEY=demo INYA_BASE_URL=http://127.0.0.1:18431/platform inya-callqa audit-live
"""

from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load_calls() -> dict[str, dict]:
    calls = {}
    for p in sorted(FIXTURES.glob("*.json")):
        for c in json.loads(p.read_text(encoding="utf-8"))["response"]:
            calls[c["conversationId"]] = c
    return calls


CALLS = load_calls()
API_KEY = "demo"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep demo output clean
        pass

    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _auth(self) -> bool:
        if self.headers.get("x-api-key") != API_KEY:
            self._send(401, {"status": "failure", "requestId": "mock", "message": "Invalid API key"})
            return False
        return True

    def _ok(self, response, message="ok") -> None:
        self._send(200, {"status": "success", "requestId": "mock-req", "message": message, "response": response})

    def do_GET(self):
        if not self._auth():
            return
        path = self.path.split("?")[0]
        if path == "/platform/v1/agents":
            bots = sorted({(c["botId"], c["botName"]) for c in CALLS.values()})
            self._ok({"pageNo": 1, "pageSize": 10, "totalCount": len(bots), "totalPages": 1,
                      "bots": [{"botId": b, "botName": n} for b, n in bots]})
        elif m := re.fullmatch(r"/platform/v1/conversations/([^/]+)/stats", path):
            c = CALLS.get(m.group(1))
            if c is None:
                self._send(404, {"status": "failure", "requestId": "mock", "message": "Conversation not found"})
            else:
                self._ok([c], "Conversation details fetched successfully")
        else:
            self._send(404, {"status": "failure", "requestId": "mock", "message": "not found"})

    def do_POST(self):
        if not self._auth():
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        path, _, qs = self.path.partition("?")
        if path == "/platform/v1/conversations/logs":
            bot = dict(p.split("=", 1) for p in qs.split("&") if "=" in p).get("botId")
            rows = [{"conversationId": c["conversationId"], "botId": c["botId"], "botName": c["botName"],
                     "startTime": c["startTime"], "endTime": c["endTime"], "transcript": []}
                    for c in CALLS.values() if not bot or c["botId"] == bot]
            page, size = body["pageNo"], body["pageSize"]
            self._ok({"pageNo": page, "pageSize": size, "totalCount": len(rows),
                      "totalPages": max(1, -(-len(rows) // size)),
                      "data": rows[(page - 1) * size: page * size]})
        elif path == "/platform/v1/agents/prompt/validate":
            vars_ = sorted(set(re.findall(r"\{\{\s*(\w+)", body.get("systemPrompt", ""))))
            self._ok({"isValidTemplate": True, "variables": vars_, "errors": []})
        else:
            self._send(404, {"status": "failure", "requestId": "mock", "message": "not found"})


def serve(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18431
    print(f"mock Inya API on http://127.0.0.1:{port}/platform", flush=True)
    serve(port).serve_forever()
