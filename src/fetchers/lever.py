from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..models import ATS, CompanyEntry, Job
from .base import Fetcher


class LeverFetcher(Fetcher):
    name = "lever"

    async def _fetch(self, client: httpx.AsyncClient, entry: CompanyEntry) -> list[Job]:
        url = f"https://api.lever.co/v0/postings/{entry.token}?mode=json"
        r = await client.get(url, timeout=30.0)
        r.raise_for_status()
        payload = r.json()  # top-level array, not wrapped

        jobs: list[Job] = []
        for raw in payload:
            cats = raw.get("categories") or {}
            location = cats.get("location", "") or ""
            departments = [v for v in [cats.get("team"), cats.get("department")] if v]

            posted_at: datetime | None = None
            created_ms = raw.get("createdAt")
            if isinstance(created_ms, (int, float)):
                posted_at = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)

            jobs.append(Job(
                id=f"lever:{entry.token}:{raw['id']}",
                company=entry.name,
                ats=ATS.LEVER,
                title=raw.get("text", ""),
                location=location,
                url=raw.get("hostedUrl") or raw.get("applyUrl", ""),
                description=raw.get("descriptionPlain", "") or raw.get("description", ""),
                posted_at=posted_at,
                departments=departments,
                tier=entry.tier,
                raw=raw,
            ))
        return jobs
