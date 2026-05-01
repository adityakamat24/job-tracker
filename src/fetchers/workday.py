from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from ..models import ATS, CompanyEntry, Job
from ..utils import html_strip
from .base import Fetcher

# 1 req/sec per tenant — some Workday instances 403 above that.
_TENANT_LOCKS: dict[str, asyncio.Semaphore] = {}
_UA = "Mozilla/5.0 (compatible; job-tracker/1.0)"
_PAGE_SIZE = 20
_MAX_PAGES = 100  # 2000 jobs hard cap per tenant per cycle (covers NVIDIA-tier orgs)


def _lock(tenant: str) -> asyncio.Semaphore:
    if tenant not in _TENANT_LOCKS:
        _TENANT_LOCKS[tenant] = asyncio.Semaphore(1)
    return _TENANT_LOCKS[tenant]


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class WorkdayFetcher(Fetcher):
    name = "workday"

    async def _fetch(self, client: httpx.AsyncClient, entry: CompanyEntry) -> list[Job]:
        tenant = entry.tenant or ""
        site = entry.site or ""
        sub = entry.subdomain or "wd1"
        base = f"https://{tenant}.{sub}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
        list_url = f"{base}/jobs"
        headers = {"User-Agent": _UA, "Accept": "application/json", "Content-Type": "application/json"}

        jobs: list[Job] = []
        offset = 0
        total: int | None = None  # Workday only reports total on page 1; treat None as unknown.
        sem = _lock(tenant)

        for _ in range(_MAX_PAGES):
            async with sem:
                r = await client.post(
                    list_url,
                    headers=headers,
                    json={"appliedFacets": {}, "limit": _PAGE_SIZE, "offset": offset, "searchText": ""},
                    timeout=30.0,
                )
                # Polite delay inside the lock so per-tenant rate stays ≤ 1 req/sec.
                await asyncio.sleep(1.0)
            r.raise_for_status()
            payload = r.json()

            postings = payload.get("jobPostings") or []
            if not postings:
                break

            if total is None:
                total = payload.get("total") or 0

            for raw in postings:
                external_path = raw.get("externalPath", "") or ""
                native_id = external_path.rsplit("/", 1)[-1] or raw.get("bulletFields", [None])[0] or raw.get("title", "")
                jobs.append(Job(
                    id=f"workday:{tenant}:{native_id}",
                    company=entry.name,
                    ats=ATS.WORKDAY,
                    title=raw.get("title", ""),
                    location=raw.get("locationsText", "") or raw.get("location", ""),
                    url=f"https://{tenant}.{sub}.myworkdayjobs.com/{site}{external_path}",
                    description="",  # backfilled in main.py only for jobs that pass the title filter
                    posted_at=_parse_iso(raw.get("postedOn")),
                    departments=[],
                    tier=entry.tier,
                    raw={**raw, "_external_path": external_path, "_workday_base": base, "_subdomain": sub, "_site": site, "_tenant": tenant},
                ))

            offset += _PAGE_SIZE
            if total and offset >= total:
                break
            if len(postings) < _PAGE_SIZE:
                break

        return jobs

    async def fetch_description(self, client: httpx.AsyncClient, job: Job) -> str:
        """Per-job detail fetch. Only call after title filter passes (saves ~90% of detail calls)."""
        meta = job.raw or {}
        base = meta.get("_workday_base")
        external_path = meta.get("_external_path") or ""
        tenant = meta.get("_tenant") or ""
        if not base or not external_path:
            return ""
        # external_path already starts with "/job/..." for most tenants — don't double up.
        suffix = external_path if external_path.startswith("/job") else f"/job{external_path}"
        url = f"{base}{suffix}"
        headers = {"User-Agent": _UA, "Accept": "application/json"}

        sem = _lock(tenant)
        async with sem:
            try:
                r = await client.get(url, headers=headers, timeout=30.0)
                r.raise_for_status()
            finally:
                await asyncio.sleep(1.0)
        payload = r.json()
        info = payload.get("jobPostingInfo") or {}
        return html_strip(info.get("jobDescription", ""))
