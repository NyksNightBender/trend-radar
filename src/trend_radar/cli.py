"""Command line: `trend-radar fetch`, `trend-radar site`, `trend-radar readme`."""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import date
from pathlib import Path

from . import readme, site
from .config import Settings
from .pipeline import run, utc_today
from .store import Store
from .wikimedia import Wikimedia


def _github_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for key, value in values.items():
                f.write(f"{key}={value}\n")


async def _fetch(store: Store, today: date, backfill: int) -> list[date]:
    async with Wikimedia.http_client() as http:
        api = Wikimedia(http)
        written = await run(store, api, Settings(), today, backfill)
        print(f"{api.requests} API requests")
        return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trend-radar")
    parser.add_argument("--data", type=Path, default=Path("data"), help="data directory")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="analyse yesterday (UTC) and any missed days")
    fetch.add_argument("--backfill", type=int, default=0, help="also fill this many past days")
    fetch.add_argument("--today", type=date.fromisoformat, default=None, help="pretend date")

    build = sub.add_parser("site", help="render the static site")
    build.add_argument("--out", type=Path, default=Path("_site"))

    sub.add_parser("readme", help="refresh the table in README.md")

    args = parser.parse_args(argv)
    store = Store(args.data)

    if args.command == "fetch":
        written = asyncio.run(_fetch(store, args.today or utc_today(), args.backfill))
        _github_output(new_days=str(len(written)), dates=" ".join(d.isoformat() for d in written))
    elif args.command == "site":
        pages = site.build(store, args.out)
        print(f"Wrote {pages} pages to {args.out}")
    elif args.command == "readme":
        days = store.days()
        if days:
            readme.update(Path("README.md"), store.load_day(days[-1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
