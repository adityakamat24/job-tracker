"""One-shot: delete recent Discord messages the bot posted, then null out the
discord_message_id in the DB so reaction sync skips them.

Use after a misfire (e.g. a normal run that flooded the channel because new
sources were added without bootstrap). Does NOT touch jobs.db's notified=1 flag
— those rows stay marked notified so they won't re-ping on the next cron.

Single-message DELETE works on the bot's own posts and only needs the bot's
default permissions. Bulk-delete would be faster but needs MANAGE_MESSAGES.

Usage:
  python -m src.purge_recent --since-hours 2          # delete last 2h of pings
  python -m src.purge_recent --since-hours 2 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

from .discord import API_BASE, _headers
from .state import State

log = logging.getLogger(__name__)

DEFAULT_DB = "jobs.db"


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
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)

    # Find every (id, message_id) we posted within the window
    with state._txn() as conn:
        rows = conn.execute(
            """
            SELECT id, company, title, discord_message_id
            FROM seen
            WHERE discord_message_id IS NOT NULL
              AND first_seen >= ?
            """,
            (cutoff,),
        ).fetchall()

    if not rows:
        log.info("nothing to purge — no rows with discord_message_id in last %dh", args.since_hours)
        return 0

    log.info("found %d candidate messages to purge (since last %dh)", len(rows), args.since_hours)

    if args.dry_run:
        for r in rows[:30]:
            log.info("  would delete: [%s] %s (msg=%s)", r["company"], r["title"], r["discord_message_id"])
        if len(rows) > 30:
            log.info("  ... and %d more", len(rows) - 30)
        return 0

    deleted = 0
    failed = 0
    cleared_ids: list[str] = []
    async with httpx.AsyncClient() as client:
        for row in rows:
            msg_id = row["discord_message_id"]
            url = f"{API_BASE}/channels/{channel_id}/messages/{msg_id}"
            try:
                r = await client.delete(url, headers=_headers(), timeout=15.0)
                if r.status_code == 429:
                    retry_after = float(r.json().get("retry_after", 1.0))
                    log.warning("discord 429 — sleeping %.2fs", retry_after)
                    await asyncio.sleep(retry_after + 0.1)
                    r = await client.delete(url, headers=_headers(), timeout=15.0)
                if r.status_code in (200, 204, 404):
                    # 404 = message already gone (manually deleted, etc.); count as success.
                    deleted += 1
                    cleared_ids.append(row["id"])
                else:
                    failed += 1
                    log.warning("delete msg=%s failed: %s %s", msg_id, r.status_code, r.text[:200])
            except Exception as e:
                failed += 1
                log.warning("delete msg=%s exception: %s", msg_id, e)
            # Discord global rate limit is 50/s; this paces well under it
            await asyncio.sleep(0.05)

    # Null out the cleared message_ids so reaction sync ignores them.
    if cleared_ids:
        with state._txn() as conn:
            conn.executemany(
                "UPDATE seen SET discord_message_id = NULL WHERE id = ?",
                [(i,) for i in cleared_ids],
            )

    log.info("purge done: deleted=%d failed=%d (rows in window=%d)", deleted, failed, len(rows))
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    p = argparse.ArgumentParser(prog="purge-recent")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--since-hours", type=int, default=2,
                   help="delete messages whose seen.first_seen falls within last N hours (default 2)")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would be deleted without touching Discord or DB")
    args = p.parse_args(argv)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())
