from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

from ..models import CompanyEntry, Job

log = logging.getLogger(__name__)


class Fetcher(ABC):
    """Each ATS adapter implements fetch(). Failures log and return [] so one bad
    company can't kill the run."""

    name: str = "fetcher"

    @abstractmethod
    async def _fetch(self, client: httpx.AsyncClient, entry: CompanyEntry) -> list[Job]:
        ...

    async def fetch(self, client: httpx.AsyncClient, entry: CompanyEntry) -> list[Job]:
        try:
            jobs = await self._fetch(client, entry)
            log.info("%s/%s fetched %d jobs", self.name, entry.name, len(jobs))
            return jobs
        except httpx.HTTPStatusError as e:
            log.warning("%s/%s HTTP %d on %s", self.name, entry.name, e.response.status_code, e.request.url)
        except Exception as e:
            log.warning("%s/%s failed: %s", self.name, entry.name, e)
        return []
