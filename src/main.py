from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .config import Config
from .discord import post_jobs
from .fetchers import fetcher_for
from .fetchers.workday import WorkdayFetcher
from .filters.pipeline import passes_body_stages, passes_title_stages
from .models import ATS, Job
from .state import State

log = logging.getLogger(__name__)

DEFAULT_CONFIG = "companies.yaml"
DEFAULT_DB = "jobs.db"


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    # httpx is noisy at INFO; quiet it.
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _fetch_all(config: Config) -> list[Job]:
    async with httpx.AsyncClient(http2=True, follow_redirects=True) as client:
        tasks = [fetcher_for(e).fetch(client, e) for e in config.companies]
        results = await asyncio.gather(*tasks, return_exceptions=False)
    flat: list[Job] = []
    for batch in results:
        flat.extend(batch)
    return flat


async def _backfill_workday_descriptions(jobs: list[Job]) -> None:
    """For Workday jobs that passed the title filter, fetch the per-job detail to
    populate `description`. Saves ~90% of detail calls vs fetching all upfront."""
    targets = [j for j in jobs if j.ats == ATS.WORKDAY and not j.description]
    if not targets:
        return

    fetcher = WorkdayFetcher()
    async with httpx.AsyncClient(http2=True, follow_redirects=True) as client:
        # Per-tenant semaphore inside fetch_description handles rate limiting.
        coros = [fetcher.fetch_description(client, j) for j in targets]
        descs = await asyncio.gather(*coros, return_exceptions=True)
    for j, d in zip(targets, descs):
        if isinstance(d, str):
            j.description = d
        else:
            log.warning("workday detail fetch failed for %s: %s", j.id, d)


async def _async_main(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    state = State(args.db)
    run_id = state.start_run()

    log.info("starting run %d (bootstrap=%s, dry_run=%s)", run_id, args.bootstrap, args.dry_run)
    fetched = await _fetch_all(config)
    log.info("fetched %d jobs across %d companies", len(fetched), len(config.companies))

    role_inc = config.filters.role_include_extra
    role_exc = config.filters.role_exclude_extra
    loc_extra = config.filters.locations_include_extra
    sp_strict = config.filters.sponsorship_strict

    # Stage 1: title-only filters (cheap)
    after_title: list[Job] = []
    rejected_role = rejected_seniority = 0
    for j in fetched:
        reason = passes_title_stages(j, role_extra_include=role_inc, role_extra_exclude=role_exc)
        if reason == "role":
            rejected_role += 1
        elif reason == "seniority":
            rejected_seniority += 1
        else:
            after_title.append(j)

    # Stage 1.5: backfill descriptions for Workday survivors
    await _backfill_workday_descriptions(after_title)

    # Stage 2: body-dependent filters
    accepted: list[Job] = []
    rejected_location = rejected_sponsorship = 0
    for j in after_title:
        reason = passes_body_stages(j, sponsorship_strict=sp_strict, location_extra=loc_extra)
        if reason == "location":
            rejected_location += 1
        elif reason == "sponsorship":
            rejected_sponsorship += 1
        else:
            accepted.append(j)

    log.info(
        "filter funnel: fetched=%d → role_ok=%d (-%d) → seniority_ok=%d (-%d) → location_ok=%d (-%d) → final=%d (-%d)",
        len(fetched),
        len(fetched) - rejected_role, rejected_role,
        len(after_title), rejected_seniority,
        len(after_title) - rejected_location, rejected_location,
        len(accepted), rejected_sponsorship,
    )

    if args.dry_run:
        for j in sorted(accepted, key=lambda j: (j.tier, j.company.lower(), j.title.lower())):
            print(f"[T{j.tier}] {j.short()}\n      {j.url}")
        log.info("dry-run finished: would notify %d jobs", len(accepted))
        state.finish_run(run_id, jobs_fetched=len(fetched), jobs_new=0, jobs_notified=0)
        return 0

    if args.replay_since:
        # One-shot backfill path: post to Discord every accepted job whose
        # posted_at >= args.replay_since, regardless of seen-state. Useful right
        # after bootstrap when the user wants today's postings to actually surface.
        try:
            since = datetime.strptime(args.replay_since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            log.error("--replay-since must be YYYY-MM-DD, got %r", args.replay_since)
            return 2

        replay_jobs = [j for j in accepted if j.posted_at and j.posted_at >= since]
        log.info("replay-since=%s: %d/%d accepted jobs are posted on/after that date",
                 args.replay_since, len(replay_jobs), len(accepted))

        # Make sure these rows exist in seen so reaction sync works on them later.
        existing = state.get_open_ids()
        for j in replay_jobs:
            if j.id not in existing:
                state.insert(j, notified=False)

        notified_count = 0
        if replay_jobs:
            channel_id = os.environ.get("DISCORD_CHANNEL_ID", "")
            if not channel_id:
                log.error("DISCORD_CHANNEL_ID env var not set; skipping replay notify")
                return 2
            async with httpx.AsyncClient(http2=True) as client:
                msg_map = await post_jobs(client, channel_id, replay_jobs)
            for jid, mid in msg_map.items():
                state.mark_notified(jid, mid)
            notified_count = len(msg_map)
            log.info("replay: notified %d/%d jobs to Discord", notified_count, len(replay_jobs))

        state.finish_run(run_id, jobs_fetched=len(fetched), jobs_new=0, jobs_notified=notified_count)
        return 0

    # Compute new vs existing vs closed
    accepted_ids = {j.id for j in accepted}
    open_ids = state.get_open_ids()
    new_ids = accepted_ids - open_ids
    closed_ids = open_ids - accepted_ids

    # Insert new (mark notified upfront in bootstrap)
    new_jobs = [j for j in accepted if j.id in new_ids]
    for j in new_jobs:
        state.insert(j, notified=args.bootstrap)

    # bulk_update_last_seen UPDATEs `last_seen=now, closed_at=NULL`. Apply to
    # ALL accepted ids (not just currently-open) so a previously-closed job
    # that reappears gets its closed_at cleared on the same cycle it's
    # re-notified. Otherwise closed_at sticks and the job re-pings every cycle.
    state.bulk_update_last_seen(accepted_ids)
    state.bulk_close(closed_ids)

    notified_count = 0
    if args.bootstrap:
        log.info("bootstrap: inserted %d new (notified=1, no Discord)", len(new_jobs))
        notified_count = 0
    elif new_jobs:
        channel_id = os.environ.get("DISCORD_CHANNEL_ID", "")
        if not channel_id:
            log.error("DISCORD_CHANNEL_ID env var not set; skipping notify")
        else:
            async with httpx.AsyncClient(http2=True) as client:
                msg_map = await post_jobs(client, channel_id, new_jobs)
            for jid, mid in msg_map.items():
                state.mark_notified(jid, mid)
            notified_count = len(msg_map)
            log.info("notified %d/%d new jobs to Discord", notified_count, len(new_jobs))
    else:
        log.info("no new jobs to notify")

    state.finish_run(
        run_id,
        jobs_fetched=len(fetched),
        jobs_new=len(new_jobs),
        jobs_notified=notified_count,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    p = argparse.ArgumentParser(prog="job-tracker")
    p.add_argument("--config", default=DEFAULT_CONFIG, help="path to companies.yaml")
    p.add_argument("--db", default=DEFAULT_DB, help="path to jobs.db")
    p.add_argument("--bootstrap", action="store_true", help="insert all current jobs as notified=1; do not send to Discord")
    p.add_argument("--dry-run", action="store_true", help="print would-be notifications; no DB writes, no Discord posts")
    p.add_argument("--replay-since", metavar="YYYY-MM-DD", help="one-shot: post to Discord every accepted job with posted_at >= this date, regardless of seen-state")
    args = p.parse_args(argv)

    if not Path(args.config).exists():
        log.error("config not found: %s", args.config)
        return 2

    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())
