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
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class AshbyFetcher(Fetcher):
    name = "ashby"

    async def _fetch(self, client: httpx.AsyncClient, entry: CompanyEntry) -> list[Job]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{entry.token}?includeCompensation=true"
        r = await client.get(url, timeout=30.0)
        r.raise_for_status()
        payload = r.json()

        jobs: list[Job] = []
        for raw in payload.get("jobs", []):
            # Prefer descriptionPlain (already clean); fall back to descriptionHtml stripped.
            description = raw.get("descriptionPlain") or html_strip(raw.get("descriptionHtml", ""))

            # Location: prefer locationName, then assemble from address.
            location = raw.get("locationName") or ""
            if not location:
                addr = (raw.get("address") or {}).get("postalAddress") or {}
                location = ", ".join(filter(None, [
                    addr.get("addressLocality"),
                    addr.get("addressRegion"),
                    addr.get("addressCountry"),
                ]))

            jobs.append(Job(
                id=f"ashby:{entry.token}:{raw['id']}",
                company=entry.name,
                ats=ATS.ASHBY,
                title=raw.get("title", ""),
                location=location,
                url=raw.get("jobUrl") or raw.get("applyUrl", ""),
                description=description,
                posted_at=_parse_iso(raw.get("publishedDate") or raw.get("publishedAt")),
                departments=[d for d in [raw.get("department"), raw.get("team")] if d],
                tier=entry.tier,
                raw=raw,
            ))
        return jobs
