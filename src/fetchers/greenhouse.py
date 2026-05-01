from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..models import ATS, CompanyEntry, Job
from ..utils import html_strip
from .base import Fetcher


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # Greenhouse: "2024-12-01T18:23:45-05:00"
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class GreenhouseFetcher(Fetcher):
    name = "greenhouse"

    async def _fetch(self, client: httpx.AsyncClient, entry: CompanyEntry) -> list[Job]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{entry.token}/jobs?content=true"
        r = await client.get(url, timeout=30.0)
        r.raise_for_status()
        payload = r.json()

        jobs: list[Job] = []
        for raw in payload.get("jobs", []):
            location = (raw.get("location") or {}).get("name", "")
            departments = [d.get("name", "") for d in raw.get("departments", []) if d.get("name")]
            posted_at = _parse_iso(raw.get("first_published") or raw.get("updated_at"))

            jobs.append(Job(
                id=f"greenhouse:{entry.token}:{raw['id']}",
                company=entry.name,
                ats=ATS.GREENHOUSE,
                title=raw.get("title", ""),
                location=location,
                url=raw.get("absolute_url", ""),
                description=html_strip(raw.get("content", "")),
                posted_at=posted_at,
                departments=departments,
                tier=entry.tier,
                raw=raw,
            ))
        return jobs
