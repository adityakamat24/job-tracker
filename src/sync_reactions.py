from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

import httpx

from .discord import fetch_reactions
from .state import State

log = logging.getLogger(__name__)

DEFAULT_DB = "jobs.db"
APPLIED_EMOJI = "✅"


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _async_main(args: argparse.Namespace) -> int:
    channel_id = os.environ.get("DISCORD_CHANNEL_ID", "")
    if not channel_id:
        log.error("DISCORD_CHANNEL_ID env var not set")
        return 2

    state = State(args.db)
    rows = state.unapplied_recent(days=args.days)
    log.info("checking reactions on %d unapplied messages (last %d days)", len(rows), args.days)

    marked = 0
    async with httpx.AsyncClient(http2=True) as client:
        for row in rows:
            users = await fetch_reactions(client, channel_id, row["discord_message_id"], APPLIED_EMOJI)
            if users:
                state.mark_applied(row["id"])
                marked += 1
                log.info("applied: [%s] %s (msg=%s, %d reactor(s))",
                         row["company"], row["title"], row["discord_message_id"], len(users))
            # gentle pacing — 50 req/sec global cap is plenty, but keep us safe
            await asyncio.sleep(0.1)

    log.info("reaction sync done: %d/%d marked applied", marked, len(rows))
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    p = argparse.ArgumentParser(prog="sync-reactions")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--days", type=int, default=30, help="only check messages from last N days")
    args = p.parse_args(argv)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())
