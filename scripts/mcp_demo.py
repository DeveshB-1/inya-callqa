"""Launch `inya-callqa serve` over stdio the way Claude Desktop would, list its
tools, and call audit_recent_calls. Point INYA_BASE_URL at the real API or at
scripts/mock_inya.py."""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import Client, StdioServerParameters


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "inya_callqa.cli", "serve"],
        env={**os.environ},
    )
    async with Client(params) as client:
        tools = await client.list_tools()
        print("tools:", ", ".join(t.name for t in tools.tools))
        res = await client.call_tool("audit_recent_calls", {"limit": 10})
        if res.is_error:
            raise SystemExit(f"tool error: {res.content[0].text}")
        data = res.structured_content or json.loads(res.content[0].text)
        print(json.dumps(data["rollup"], indent=2))
        for call in data["calls"]:
            top = call["findings"][0]
            print(f"{call['conversation_id']}: {len(call['findings'])} findings, "
                  f"first = {top['check']} {top['evidence']!r}")


if __name__ == "__main__":
    asyncio.run(main())
