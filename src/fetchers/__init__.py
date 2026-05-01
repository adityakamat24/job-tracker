from __future__ import annotations

from ..models import ATS, CompanyEntry
from .base import Fetcher
from .ashby import AshbyFetcher
from .greenhouse import GreenhouseFetcher
from .lever import LeverFetcher
from .workable import WorkableFetcher
from .workday import WorkdayFetcher

_REGISTRY: dict[ATS, Fetcher] = {
    ATS.GREENHOUSE: GreenhouseFetcher(),
    ATS.ASHBY: AshbyFetcher(),
    ATS.LEVER: LeverFetcher(),
    ATS.WORKDAY: WorkdayFetcher(),
    ATS.WORKABLE: WorkableFetcher(),
}


def fetcher_for(entry: CompanyEntry) -> Fetcher:
    return _REGISTRY[entry.ats]
