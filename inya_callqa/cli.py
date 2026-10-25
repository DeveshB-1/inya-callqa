from __future__ import annotations

import argparse
import json
import sys

from .audit import CallReport, audit_call, calls_from_payload, rollup


def render(reports: list[CallReport]) -> str:
    lines = []
    for r in reports:
        lines.append(f"call {r.conversation_id}  bot={r.bot_name}  status={r.call_status}  "
                     f"disposition={r.disposition}")
        lines.append(f"  turns={r.turns} user_turns={r.user_turns} languages={r.languages} "
                     f"code_mixed_turns={r.code_mixed_turns} interruptions={r.interruptions} "
                     f"max_agent_gap={r.max_agent_gap_s}s")
        if not r.findings:
            lines.append("  no findings")
        for f in r.findings:
            where = f"turn {f.turn}" if f.turn >= 0 else "call"
            lines.append(f"  [{f.severity.upper():6}] {f.check:28} {where:8} {f.evidence}")
        lines.append("")
    ru = rollup(reports)
    lines.append(f"rollup: {ru['calls']} calls, {ru['user_turns']} user turns, "
                 f"code-mixed share {ru['code_mixed_turn_share']:.0%}, "
                 f"{ru['calls_with_high_severity']} calls with HIGH findings")
    for check, n in ru["calls_affected_by_check"].items():
        lines.append(f"  {check:28} {n}/{ru['calls']} calls")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="inya-callqa", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="audit saved Stats API JSON files (no API key needed)")
    a.add_argument("files", nargs="+")
    a.add_argument("--json", action="store_true")
    a.add_argument("--threshold", type=float, default=0.75)

    live = sub.add_parser("audit-live", help="pull recent calls from the Inya API and audit them")
    live.add_argument("--bot-id")
    live.add_argument("--limit", type=int, default=20)
    live.add_argument("--start-date")
    live.add_argument("--end-date")
    live.add_argument("--json", action="store_true")
    live.add_argument("--threshold", type=float, default=0.75)

    sub.add_parser("serve", help="run the MCP server on stdio")

    args = p.parse_args(argv)
    if args.cmd == "serve":
        from .server import main as serve
        serve()
        return 0

    if args.cmd == "audit":
        calls = []
        for path in args.files:
            with open(path, encoding="utf-8") as fh:
                calls += calls_from_payload(json.load(fh))
    else:
        from .client import InyaClient
        with InyaClient() as c:
            calls = c.recent_calls(limit=args.limit, bot_id=args.bot_id, start_date=args.start_date,
                                   end_date=args.end_date, call_status="ANSWERED")

    reports = [audit_call(c, disagreement_threshold=args.threshold) for c in calls]
    if args.json:
        json.dump({"rollup": rollup(reports), "calls": [r.to_dict() for r in reports]},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print(render(reports))
    return 1 if any(f.severity == "high" for r in reports for f in r.findings) else 0


if __name__ == "__main__":
    sys.exit(main())
