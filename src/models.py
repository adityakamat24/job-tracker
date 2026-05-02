from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ATS(str, Enum):
    GREENHOUSE = "greenhouse"
    ASHBY = "ashby"
    LEVER = "lever"
    WORKDAY = "workday"
    WORKABLE = "workable"
    SMARTRECRUITERS = "smartrecruiters"
    GITHUB_LIST = "github_list"


@dataclass
class Job:
    id: str                              # namespaced: f"{ats}:{token-or-tenant}:{native_id}"
    company: str                         # display name, e.g. "Anthropic"
    ats: ATS
    title: str
    location: str                        # raw string from API
    url: str                             # apply URL
    description: str = ""                # plain-text, HTML stripped, for sponsorship scan
    posted_at: datetime | None = None
    departments: list[str] = field(default_factory=list)
    tier: int = 3                        # carried from CompanyEntry, used for sort order + embed color
    raw: dict = field(default_factory=dict)

    def short(self) -> str:
        return f"[{self.company}] {self.title} — {self.location}"


@dataclass
class CompanyEntry:
    """Validated row from companies.yaml. Per-ATS fields live here so fetchers stay simple."""
    name: str
    ats: ATS
    tier: int = 3
    notes: str = ""
    # greenhouse / ashby / lever / workable / smartrecruiters
    token: str | None = None
    # workday
    tenant: str | None = None
    site: str | None = None
    subdomain: str = "wd1"
    # github_list
    repo: str | None = None
    branch: str = "main"
    path: str = "README.md"

    def slug(self) -> str:
        """Used in the namespaced job ID — distinguishes companies that share an ATS."""
        return self.token or self.tenant or (self.repo or "").replace("/", "_") or self.name.lower().replace(" ", "-")
