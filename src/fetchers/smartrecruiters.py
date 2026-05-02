from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from ..models import ATS, CompanyEntry, Job
from ..utils import html_strip
from .base import Fetcher

_PAGE_SIZE = 100
_MAX_PAGES = 20  # 2000 jobs hard cap per tenant per cycle


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class SmartRecruitersFetcher(Fetcher):
    """SmartRecruiters public API. List endpoint returns title + location + ref
    but NOT the description body — we defer description fetch via the per-posting
    `ref` URL only for jobs that survive the title filter (same pattern as Workday)."""

    name = "smartrecruiters"

    async def _fetch(self, client: httpx.AsyncClient, entry: CompanyEntry) -> list[Job]:
        token = entry.token
        base = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
        jobs: list[Job] = []
        offset = 0

        for _ in range(_MAX_PAGES):
            r = await client.get(f"{base}?limit={_PAGE_SIZE}&offset={offset}", timeout=30.0)
            r.raise_for_status()
            payload = r.json()

            content = payload.get("content") or []
            if not content:
                break

            for raw in content:
                loc = raw.get("location") or {}
                location = loc.get("fullLocation") or ", ".join(filter(None, [
                    loc.get("city"), loc.get("region"), loc.get("country"),
                ]))

                department = []
                if isinstance(raw.get("department"), dict):
                    label = raw["department"].get("label")
                    if label:
                        department.append(label)

                jobs.append(Job(
                    id=f"smartrecruiters:{token}:{raw.get('id', '')}",
                    company=entry.name,
                    ats=ATS.SMARTRECRUITERS,
                    title=raw.get("name", ""),
                    location=location,
                    url=f"https://jobs.smartrecruiters.com/{token}/{raw.get('id', '')}",
                    description="",  # backfilled in main.py only for jobs that pass title filter
                    posted_at=_parse_iso(raw.get("releasedDate")),
                    departments=department,
                    tier=entry.tier,
                    raw={**raw, "_sr_ref": raw.get("ref"), "_sr_token": token},
                ))

            total = payload.get("totalFound") or 0
            offset += _PAGE_SIZE
            if total and offset >= total:
                break

        return jobs

    async def fetch_description(self, client: httpx.AsyncClient, job: Job) -> str:
        """Per-job detail fetch. Only call after title filter passes."""
        ref = (job.raw or {}).get("_sr_ref")
        if not ref:
            return ""
        try:
            r = await client.get(ref, timeout=30.0)
            r.raise_for_status()
        except Exception:
            return ""
        payload = r.json()
        # SR detail nests description sections inside `jobAd.sections.{jobDescription,qualifications,additionalInformation}`
        ad = payload.get("jobAd") or {}
        sections = ad.get("sections") or {}
        parts: list[str] = []
        for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
            section = sections.get(key) or {}
            text = section.get("text", "")
            if text:
                parts.append(text)
        return html_strip(" ".join(parts))
