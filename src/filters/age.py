from __future__ import annotations

from datetime import datetime, timedelta, timezone


def passes_age(posted_at: datetime | None, max_age_days: int) -> bool:
    """Reject jobs whose `posted_at` is older than `max_age_days`.

    Unknown (`posted_at is None`) is allowed through so a fetcher that fails to
    populate the field can't silently nuke an entire company. The role /
    location / sponsorship filters still gate those rows. Set `max_age_days <= 0`
    to disable the filter entirely.

    Future-dated postings are rejected outright. A real "freshly posted job" has
    posted_at <= now; anything in the future is a parser error (github_list
    sometimes misreads deadline / open-until columns as posted-at, producing
    Discord embeds like "in 14 days"). Reject so they don't reach the channel.
    """
    if max_age_days <= 0:
        return True
    if posted_at is None:
        return True
    now = datetime.now(timezone.utc)
    if posted_at > now:
        return False
    cutoff = now - timedelta(days=max_age_days)
    return posted_at >= cutoff
