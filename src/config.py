from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from .models import ATS, CompanyEntry

log = logging.getLogger(__name__)


class _CompanyRow(BaseModel):
    name: str
    ats: Literal["greenhouse", "ashby", "lever", "workday", "workable"]
    tier: int = 3
    notes: str = ""
    token: str | None = None
    tenant: str | None = None
    site: str | None = None
    subdomain: str = "wd1"

    @model_validator(mode="after")
    def _check_per_ats_fields(self) -> "_CompanyRow":
        if self.ats == "workday":
            if not self.tenant or not self.site:
                raise ValueError("workday entries require both 'tenant' and 'site'")
        else:
            if not self.token:
                raise ValueError(f"{self.ats} entries require 'token'")
        return self


class _FiltersBlock(BaseModel):
    role_include_extra: list[str] = Field(default_factory=list)
    role_exclude_extra: list[str] = Field(default_factory=list)
    locations_include_extra: list[str] = Field(default_factory=list)
    sponsorship_strict: bool = True


class _Root(BaseModel):
    companies: list[dict]
    filters: _FiltersBlock = Field(default_factory=_FiltersBlock)


class Config:
    """Parsed companies.yaml. Invalid entries log a warning and are skipped."""

    def __init__(self, companies: list[CompanyEntry], filters: _FiltersBlock):
        self.companies = companies
        self.filters = filters

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        root = _Root.model_validate(raw)

        entries: list[CompanyEntry] = []
        for row in root.companies:
            try:
                parsed = _CompanyRow.model_validate(row)
            except ValidationError as e:
                log.warning("skipping invalid company entry %r: %s", row.get("name", row), e)
                continue
            entries.append(CompanyEntry(
                name=parsed.name,
                ats=ATS(parsed.ats),
                tier=parsed.tier,
                notes=parsed.notes,
                token=parsed.token,
                tenant=parsed.tenant,
                site=parsed.site,
                subdomain=parsed.subdomain,
            ))

        log.info("loaded %d company entries", len(entries))
        return cls(entries, root.filters)
