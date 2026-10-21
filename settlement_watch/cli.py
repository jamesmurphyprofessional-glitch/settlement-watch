from __future__ import annotations

import argparse
import os
import sys

from settlement_watch import __version__
from settlement_watch.courtlistener import CourtListenerError
from settlement_watch.engine import DEFAULT_FIXTURE, DEFAULT_WATCHLIST, run_scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="settlement-watch",
        description=(
            "Search public US court dockets for a watchlist of people and companies, "
            "score settlement-like activity for tax-characterization red flags, "
            "and write an analyst spreadsheet. This is a screening tool, not a finding."
        ),
    )
    parser.add_argument("--version", action="version", version=f"Roach Detector {__version__}")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="Run a watchlist against public dockets.")
    check.add_argument(
        "--watchlist",
        default=str(DEFAULT_WATCHLIST),
        help="CSV with columns name, entity_type, aliases, notes.",
    )
    check.add_argument(
        "--out",
        default="output",
        help="Directory for the spreadsheet and interchange files.",
    )
    check.add_argument(
        "--token",
        default=os.environ.get("COURT_LISTENER_TOKEN", ""),
        help="CourtListener API token (or set COURT_LISTENER_TOKEN).",
    )
    check.add_argument(
        "--max-per-name",
        type=int,
        default=25,
        help="Maximum dockets to keep per watchlist name (default 25).",
    )
    check.add_argument(
        "--demo",
        action="store_true",
        help="Score bundled sample dockets instead of calling CourtListener.",
    )
    check.add_argument(
        "--fixture",
        default=str(DEFAULT_FIXTURE),
        help="JSON fixture used with --demo.",
    )
    return parser


def run_check(args: argparse.Namespace) -> int:
    try:
        scan = run_scan(
            args.watchlist,
            args.out,
            demo=args.demo,
            token=args.token or "",
            max_per_name=args.max_per_name,
            fixture=args.fixture,
            progress=lambda msg: print(msg),
        )
    except CourtListenerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "Tip: run with --demo to generate a sample spreadsheet without an API token.",
            file=sys.stderr,
        )
        return 2

    flagged = [item for item in scan.results if item.risk_band in {"MEDIUM", "HIGH"}]
    print(f"Scored {len(scan.results)} docket match(es).")
    print(f"Flagged for review (MEDIUM/HIGH): {len(flagged)}.")
    print(f"Spreadsheet: {scan.paths['xlsx']}")
    print(f"CSV:         {scan.paths['csv']}")
    print(f"JSON:        {scan.paths['json']}")
    print(f"Narratives:  {scan.paths['narratives']}")
    print("Reminder: flags are leads for review, not a determination of tax evasion.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        print("\nNo command given. Running bundled demo so you still get a spreadsheet.\n")
        args = parser.parse_args(["check", "--demo"])
    if args.command == "check":
        return run_check(args)
    parser.print_help()
    return 1
