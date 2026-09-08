from __future__ import annotations

import argparse
import sys

from companyresearch.config import settings


def _cli(query: str) -> int:
    from companyresearch.memo import write_memo
    from companyresearch.pipeline import run_research

    packet = run_research(query, on_progress=lambda step, label: print(f"... {label}", file=sys.stderr))
    memo, engine = write_memo(packet)
    print(memo)
    print(f"\n---\nEngine: {engine}", file=sys.stderr)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Company research briefing (not investment advice).")
    parser.add_argument("query", nargs="?", help="Ticker or company name. Omit to start the web app.")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--autopilot", action="store_true", help="One pretend helper pass, then exit.")
    parser.add_argument("--scoreboard", default="", help="Write a phone HTML scoreboard to this folder.")
    args = parser.parse_args()
    if args.autopilot:
        from companyresearch.paper import autopilot

        out = autopilot()
        print(
            f"total={out.get('total_gbp')} profit={out.get('profit_gbp')} cash={out.get('cash_gbp')}",
            file=sys.stderr,
        )
        if args.scoreboard:
            from companyresearch.scoreboard import write_scoreboard

            path = write_scoreboard(args.scoreboard)
            print(f"scoreboard={path}", file=sys.stderr)
        return
    if args.scoreboard and not args.query:
        from companyresearch.scoreboard import write_scoreboard

        path = write_scoreboard(args.scoreboard)
        print(path)
        return
    if args.query:
        raise SystemExit(_cli(args.query))
    import uvicorn

    uvicorn.run("companyresearch.web:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
