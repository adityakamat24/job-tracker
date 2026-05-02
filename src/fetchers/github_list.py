from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from ..models import ATS, CompanyEntry, Job
from .base import Fetcher

log = logging.getLogger(__name__)

# `[text](url)` markdown link
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
# `<a href="url">text</a>` HTML link (used in some lists)
_HTML_A = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
# Closed/expired markers we want to skip outright
_SKIP_MARKERS = ("🔒", "❌")
# `5d` / `2mo` / `15h` style relative ages
_REL_AGE = re.compile(r"^\s*(\d+)\s*(d|h|mo|w|y)\s*$", re.IGNORECASE)
# `Apr 25` / `May 1` style absolute dates
_ABS_DATE = re.compile(r"^\s*([A-Z][a-z]{2})\s+(\d{1,2})\s*$")
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def _stable_id(repo: str, company: str, title: str, url: str) -> str:
    h = hashlib.sha1(f"{company}|{title}|{url}".encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"github_list:{repo.replace('/', '_')}:{h}"


def _extract_url(cell: str) -> str:
    """Best-effort apply-URL extraction from a markdown table cell."""
    m = _MD_LINK.search(cell)
    if m:
        return m.group(2).strip()
    m = _HTML_A.search(cell)
    if m:
        return m.group(1).strip()
    return ""


def _strip_markdown(cell: str) -> str:
    """Replace `[text](url)` with `text`, drop HTML tags, collapse whitespace."""
    cell = _MD_LINK.sub(lambda m: m.group(1), cell)
    cell = re.sub(r"<[^>]+>", "", cell)
    cell = cell.replace("**", "").replace("*", "").replace("`", "")
    return re.sub(r"\s+", " ", cell).strip()


def _parse_age(cell: str) -> datetime | None:
    text = _strip_markdown(cell)
    if not text:
        return None
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    m = _REL_AGE.match(text)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit == "h":
            return today
        if unit == "d":
            return today - timedelta(days=n)
        if unit == "w":
            return today - timedelta(weeks=n)
        if unit == "mo":
            return today - timedelta(days=n * 30)
        if unit == "y":
            return today - timedelta(days=n * 365)
    m = _ABS_DATE.match(text)
    if m:
        month = _MONTHS.get(m.group(1).title())
        if month:
            day = int(m.group(2))
            year = today.year
            try:
                dt = datetime(year, month, day, tzinfo=timezone.utc)
                # If the parsed date is more than ~30 days in the future, it's
                # probably last year (e.g. parsed in early Jan).
                if (dt - today).days > 30:
                    dt = dt.replace(year=year - 1)
                return dt
            except ValueError:
                return None
    return None


def _parse_markdown_table_rows(markdown: str) -> list[list[str]]:
    """Find every markdown pipe-table in the document, return all data rows."""
    rows: list[list[str]] = []
    in_table = False
    saw_separator = False
    for line in markdown.splitlines():
        line = line.rstrip()
        if not line.startswith("|"):
            in_table = False
            saw_separator = False
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if all(re.match(r"^:?-+:?$", p) for p in parts if p):
            in_table = True
            saw_separator = True
            continue
        if not saw_separator:
            continue
        if in_table:
            rows.append(parts)
    return rows


_HTML_TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.IGNORECASE)
_HTML_TD = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.S | re.IGNORECASE)


def _parse_html_table_rows(text: str) -> list[list[str]]:
    """SimplifyJobs and similar repos use HTML <table>/<tr>/<td> tags inside the
    README rather than markdown pipes. Extract every <tr>'s <td> children as raw
    cell content (HTML preserved — caller strips it)."""
    rows: list[list[str]] = []
    for tr_match in _HTML_TR.finditer(text):
        cells = [c.strip() for c in _HTML_TD.findall(tr_match.group(1))]
        if not cells:
            continue
        # Header rows use <th> — _HTML_TD captures them too; skip if any cell looks like a header label.
        joined_lower = " ".join(cells).lower()
        if "company" in joined_lower and "role" in joined_lower and "location" in joined_lower:
            continue
        rows.append(cells)
    return rows


def _parse_table_rows(text: str) -> list[list[str]]:
    """Try markdown first, fall back to HTML table parsing."""
    rows = _parse_markdown_table_rows(text)
    if rows:
        return rows
    return _parse_html_table_rows(text)


class GitHubListFetcher(Fetcher):
    """Pulls a curated job list from a public GitHub repo's README markdown.
    Designed for SimplifyJobs/New-Grad-Positions and similar tables.

    Schema (typical, SimplifyJobs-style):
      | Company | Role | Location | Application | Age |

    Quirks handled:
      - `↳` in Company column = use previous row's company name.
      - 🔒 / ❌ markers = skip (closed/expired).
      - 🇺🇸 / 🛂 stay in the title; the role filter rejects them at stage 1.
    """

    name = "github_list"

    async def _fetch(self, client: httpx.AsyncClient, entry: CompanyEntry) -> list[Job]:
        if not entry.repo:
            return []
        url = f"https://raw.githubusercontent.com/{entry.repo}/{entry.branch}/{entry.path}"
        r = await client.get(url, timeout=30.0)
        r.raise_for_status()
        markdown = r.text

        rows = _parse_table_rows(markdown)
        if not rows:
            log.warning("github_list/%s: no markdown table found", entry.name)
            return []

        jobs: list[Job] = []
        prev_company = ""
        for cells in rows:
            if len(cells) < 4:
                continue  # malformed row

            company_cell = cells[0]
            title_cell = cells[1]
            location_cell = cells[2]
            apply_cell = cells[3]
            age_cell = cells[4] if len(cells) >= 5 else ""

            # Skip closed/expired
            joined = " ".join(cells)
            if any(marker in joined for marker in _SKIP_MARKERS):
                continue

            # Resolve `↳` continuation
            company = _strip_markdown(company_cell)
            if company in ("↳", "->", ""):
                company = prev_company
            else:
                prev_company = company

            if not company:
                continue

            title = _strip_markdown(title_cell)
            location = _strip_markdown(location_cell)
            apply_url = _extract_url(apply_cell)
            if not apply_url:
                # Some lists put the URL inside the role cell instead
                apply_url = _extract_url(title_cell)
            if not title or not apply_url:
                continue

            posted_at = _parse_age(age_cell)

            jobs.append(Job(
                id=_stable_id(entry.repo, company, title, apply_url),
                company=company,
                ats=ATS.GITHUB_LIST,
                title=title,
                location=location,
                url=apply_url,
                description="",  # not available from the list
                posted_at=posted_at,
                departments=[],
                tier=entry.tier,
                raw={"_repo": entry.repo, "_source_company": entry.name},
            ))

        return jobs
