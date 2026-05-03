from __future__ import annotations

import logging
from dataclasses import dataclass

from ..models import Job
from .age import passes_age
from .location import passes_location
from .role import passes_role
from .seniority import passes_seniority
from .sponsorship import passes_sponsorship

log = logging.getLogger(__name__)


@dataclass
class FilterStats:
    fetched: int = 0
    rejected_age: int = 0
    rejected_role: int = 0
    rejected_seniority: int = 0
    rejected_location: int = 0
    rejected_sponsorship: int = 0
    accepted: int = 0


def passes_title_stages(job: Job, *, max_age_days: int,
                        role_extra_include: list[str] | None = None,
                        role_extra_exclude: list[str] | None = None) -> str | None:
    """Run the cheap title-only filters. Returns reject-reason or None if accepted so far."""
    if not passes_age(job.posted_at, max_age_days):
        return "age"
    if not passes_role(job.title, extra_include=role_extra_include, extra_exclude=role_extra_exclude):
        return "role"
    if not passes_seniority(job.title):
        return "seniority"
    return None


def passes_body_stages(job: Job, *, sponsorship_strict: bool,
                       location_extra: list[str] | None = None) -> str | None:
    """Run the body-dependent filters (location + sponsorship). Returns reject-reason or None."""
    if not passes_location(job.location, job.description, extra_include=location_extra, title=job.title):
        return "location"
    if sponsorship_strict and not passes_sponsorship(job.description, job_title=job.title, company=job.company):
        return "sponsorship"
    return None
