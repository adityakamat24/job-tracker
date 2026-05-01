from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..models import ATS, CompanyEntry, Job
from .base import Fetcher


def _parse_date(s: str | None) -> datetime | None:
    """Workable returns dates like '2026-02-12'."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class WorkableFetcher(Fetcher):
    """Workable widget API. Returns title + location but NOT description.
    Sponsorship filter degrades gracefully on empty descriptions (passes through).
    The title-fallback location filter does the heavy lifting for non-US rejection."""

    name = "workable"

    async def _fetch(self, client: httpx.AsyncClient, entry: CompanyEntry) -> list[Job]:
        url = f"https://apply.workable.com/api/v1/widget/accounts/{entry.token}"
        r = await client.get(url, timeout=30.0)
        r.raise_for_status()
        payload = r.json()

        jobs: list[Job] = []
        for raw in payload.get("jobs", []):
            location_parts = [p for p in (raw.get("city"), raw.get("state"), raw.get("country")) if p]
            location = ", ".join(location_parts)
            if raw.get("telecommuting") and location:
                location = f"{location} (remote)"
            elif raw.get("telecommuting"):
                location = "Remote"

            departments = [d for d in [raw.get("department")] if d]

            jobs.append(Job(
                id=f"workable:{entry.token}:{raw.get('shortcode', '')}",
                company=entry.name,
                ats=ATS.WORKABLE,
                title=raw.get("title", ""),
                location=location,
                url=raw.get("url") or raw.get("application_url", ""),
                description="",  # widget API doesn't expose description
                posted_at=_parse_date(raw.get("published_on")),
                departments=departments,
                tier=entry.tier,
                raw=raw,
            ))
        return jobs
