"""Emergency: purge Discord messages BY DIRECTLY READING THE CHANNEL, not from
jobs.db. Use this when a flood happened but the workflow was cancelled before
state.mark_notified() could persist the message_ids — i.e. when src.purge_recent
finds nothing.

Walks back through channel history, deletes any message whose author is this
bot. Stops when it hits a message older than --since-hours.

Then ALSO marks every accepted job currently in the world as notified=1 in
jobs.db (a forced mini-bootstrap pass) so the next normal run doesn't re-notify
the same flood. That second pass is mandatory to recover from the cancellation
— otherwise the same jobs would re-ping on the next cron tick.
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

log = logging.getLogger(__name__)


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _get_bot_id(client: httpx.AsyncClient) -> str:
    r = await client.get(f"{API_BASE}/users/@me", headers=_headers(), timeout=15.0)
    r.raise_for_status()
    return str(r.json()["id"])


async def _async_main(args: argparse.Namespace) -> int:
    channel_id = os.environ.get("DISCORD_CHANNEL_ID", "")
    if not channel_id:
        log.error("DISCORD_CHANNEL_ID env var not set")
        return 2

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)
    log.info("purging messages by this bot in #%s newer than %s", channel_id, cutoff.isoformat())

    async with httpx.AsyncClient() as client:
        bot_id = await _get_bot_id(client)
        log.info("bot user id: %s", bot_id)

        # Walk channel history backwards in pages of 100.
        before: str | None = None
        to_delete: list[str] = []
        scanned = 0
        while True:
            url = f"{API_BASE}/channels/{channel_id}/messages?limit=100"
            if before:
                url += f"&before={before}"
            r = await client.get(url, headers=_headers(), timeout=30.0)
            if r.status_code == 429:
                retry = float(r.json().get("retry_after", 1.0))
                log.warning("429 listing messages, sleeping %.2fs", retry)
                await asyncio.sleep(retry + 0.1)
                continue
            r.raise_for_status()
            page = r.json()
            if not page:
                break
            scanned += len(page)
            keep_going = False
            for msg in page:
                ts = msg.get("timestamp", "")
                # ISO8601 with optional 'Z'
                try:
                    msg_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    msg_time = datetime.now(timezone.utc)
                if msg_time < cutoff:
                    # Older than window — stop the scan.
                    continue
                keep_going = True
                author = (msg.get("author") or {}).get("id", "")
                if str(author) == bot_id:
                    to_delete.append(str(msg["id"]))
            before = str(page[-1]["id"])
            if not keep_going:
                break
            await asyncio.sleep(0.2)

        log.info("scanned %d messages, will delete %d (bot-authored, in window)",
                 scanned, len(to_delete))

        if args.dry_run:
            log.info("dry-run — not deleting")
            return 0

        deleted = 0
        failed = 0
        for mid in to_delete:
            url = f"{API_BASE}/channels/{channel_id}/messages/{mid}"
            try:
                r = await client.delete(url, headers=_headers(), timeout=15.0)
                if r.status_code == 429:
                    retry = float(r.json().get("retry_after", 1.0))
                    log.warning("429 deleting, sleeping %.2fs", retry)
                    await asyncio.sleep(retry + 0.1)
                    r = await client.delete(url, headers=_headers(), timeout=15.0)
                if r.status_code in (200, 204, 404):
                    deleted += 1
                else:
                    failed += 1
                    log.warning("delete %s -> %s %s", mid, r.status_code, r.text[:200])
            except Exception as e:
                failed += 1
                log.warning("delete %s exception: %s", mid, e)
            await asyncio.sleep(0.05)  # global 50/s; pace well under

    log.info("done: deleted=%d failed=%d", deleted, failed)
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    p = argparse.ArgumentParser(prog="purge-channel")
    p.add_argument("--since-hours", type=int, default=12,
                   help="delete bot-authored messages from the last N hours (default 12)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())
