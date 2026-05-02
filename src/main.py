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

# Safety cap: a normal run that wants to notify more than this many jobs is
# almost certainly a misconfiguration (new sources added without bootstrap, or
# something else wrong). Refuse to flood; mark them all as notified=1 instead
# so the next run is quiet, and require explicit `--bootstrap` or manual
# investigation. Bootstrap mode + auto-bootstrap (first-touch) are exempt.
MAX_NOTIFY_PER_RUN = 50


def _source_key(job_id: str) -> str:
    """Turn `greenhouse:anthropic:1234` into `greenhouse:anthropic`. Used to
    match a job back to its CompanyEntry's (ats, slug) pair."""
    parts = job_id.split(":", 2)
    if len(parts) < 2:
        return job_id
    return f"{parts[0]}:{parts[1]}"


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
    return _dedupe_cross_source(flat)


def _dedupe_cross_source(jobs: list[Job]) -> list[Job]:
    """Same role can appear across multiple sources (direct ATS + a curated
    GitHub list, etc.). Collapse by (company, title) — case-insensitive — and
    prefer the entry with a non-empty description so downstream filters
    (sponsorship in particular) have something to work with."""
    bucket: dict[tuple[str, str], Job] = {}
    for j in jobs:
        key = (j.company.strip().lower(), j.title.strip().lower())
        existing = bucket.get(key)
        if existing is None:
            bucket[key] = j
            continue
        if not existing.description and j.description:
            bucket[key] = j
    deduped = list(bucket.values())
    if len(deduped) < len(jobs):
        log.info("cross-source dedupe: %d → %d (collapsed %d duplicates)",
                 len(jobs), len(deduped), len(jobs) - len(deduped))
    return deduped


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

    # First-touch detection: if a source (ats:slug) has zero rows in `seen`,
    # this is its very first appearance. Pinging its entire backlog would
    # flood the channel. Auto-absorb instead: insert as notified=1, no Discord.
    # Eliminates the "you forgot to bootstrap when adding new companies" trap.
    known_sources = state.get_known_source_keys()
    new_jobs = [j for j in accepted if j.id in new_ids]
    auto_bootstrap_jobs = []
    real_new_jobs = []
    for j in new_jobs:
        if _source_key(j.id) not in known_sources:
            auto_bootstrap_jobs.append(j)
        else:
            real_new_jobs.append(j)

    if auto_bootstrap_jobs:
        first_touch_sources = sorted({_source_key(j.id) for j in auto_bootstrap_jobs})
        log.info("first-touch sources auto-bootstrapping (%d jobs across %d sources): %s",
                 len(auto_bootstrap_jobs), len(first_touch_sources), first_touch_sources)
        for j in auto_bootstrap_jobs:
            state.insert(j, notified=True)

    # Insert real-new with notified flag determined by --bootstrap
    for j in real_new_jobs:
        state.insert(j, notified=args.bootstrap)

    # Refresh last_seen / clear closed_at on every accepted id (not just open),
    # so a previously-closed job that reappears gets cleared on the same cycle
    # it's re-notified.
    state.bulk_update_last_seen(accepted_ids)
    state.bulk_close(closed_ids)

    # Safety cap: even after first-touch protection, refuse to ping more than
    # MAX_NOTIFY_PER_RUN in a single normal run. If this trips, something's
    # wrong (broken filter, new ATS adapter, etc.) — mark them all notified to
    # prevent flood and surface in logs for manual investigation.
    notified_count = 0
    if args.bootstrap:
        total_inserted = len(auto_bootstrap_jobs) + len(real_new_jobs)
        log.info("bootstrap: inserted %d new (auto=%d + explicit=%d), no Discord",
                 total_inserted, len(auto_bootstrap_jobs), len(real_new_jobs))
    elif real_new_jobs and len(real_new_jobs) > MAX_NOTIFY_PER_RUN:
        log.error(
            "SAFETY CAP TRIPPED: %d real-new jobs > MAX_NOTIFY_PER_RUN=%d. "
            "Refusing to flood Discord. Marking all as notified=1 silently. "
            "Investigate: did filter logic change? new ATS adapter? "
            "Trigger workflow with bootstrap=true to re-baseline if expected.",
            len(real_new_jobs), MAX_NOTIFY_PER_RUN,
        )
        state.mark_notified_no_message([j.id for j in real_new_jobs])
    elif real_new_jobs:
        channel_id = os.environ.get("DISCORD_CHANNEL_ID", "")
        if not channel_id:
            log.error("DISCORD_CHANNEL_ID env var not set; skipping notify")
        else:
            async with httpx.AsyncClient(http2=True) as client:
                msg_map = await post_jobs(client, channel_id, real_new_jobs)
            for jid, mid in msg_map.items():
                state.mark_notified(jid, mid)
            notified_count = len(msg_map)
            log.info("notified %d/%d real-new jobs to Discord (auto-bootstrapped %d)",
                     notified_count, len(real_new_jobs), len(auto_bootstrap_jobs))
    else:
        log.info("no real-new jobs to notify (auto-bootstrapped %d)", len(auto_bootstrap_jobs))

    state.finish_run(
        run_id,
        jobs_fetched=len(fetched),
        jobs_new=len(real_new_jobs),
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
