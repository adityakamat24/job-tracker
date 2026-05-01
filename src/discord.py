from __future__ import annotations

import asyncio
import logging
import os
from typing import Iterable

import httpx

from .models import Job
from .utils import extract_comp

log = logging.getLogger(__name__)

API_BASE = "https://discord.com/api/v10"
EMBEDS_PER_MESSAGE = 10  # Discord cap
TIER_COLORS: dict[int, int] = {1: 5814783, 2: 5763719, 3: 10070709}
TIER_EMOJI: dict[int, str] = {1: "🥇", 2: "🥈", 3: "🥉"}
DESC_EXCERPT_CHARS = 220


def _headers() -> dict[str, str]:
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN env var not set")
    return {"Authorization": f"Bot {token}", "Content-Type": "application/json", "User-Agent": "job-tracker (https://github.com, 1.0)"}


def _format_embed(job: Job) -> dict:
    """One Discord embed per job. Optimised for skim-then-click:
    - tier emoji prefix in the title
    - subtitle with company/location/posted-time on a single line
    - description excerpt (first ~220 chars of the JD) so the user can triage
      without opening the link
    - inline comp + team fields when extractable
    - reaction-cheatsheet footer so the user remembers ✅ / 🚫 / 📝"""

    emoji = TIER_EMOJI.get(job.tier, "•")
    title = f"{emoji} {(job.title or 'Untitled')}"[:256]

    subtitle_parts: list[str] = [f"**{job.company}**" if job.company else "**?**"]
    if job.location:
        subtitle_parts.append(job.location)
    if job.posted_at:
        subtitle_parts.append(f"<t:{int(job.posted_at.timestamp())}:R>")
    description_text = " · ".join(subtitle_parts)

    if job.description:
        cleaned = job.description.strip()
        excerpt = cleaned[:DESC_EXCERPT_CHARS].rstrip()
        if len(cleaned) > DESC_EXCERPT_CHARS:
            excerpt += "…"
        description_text = f"{description_text}\n\n{excerpt}"

    # Discord embed.description cap is 4096; we're well under.
    description_text = description_text[:4096]

    fields: list[dict] = []
    comp = extract_comp(job.description)
    if comp:
        fields.append({"name": "💰 Comp", "value": comp, "inline": True})
    if job.departments:
        team = ", ".join(job.departments)
        fields.append({"name": "🏷️ Team", "value": team[:1024], "inline": True})

    footer = f"✅ applied  ·  🚫 skip  ·  📝 tailor   |   via {job.ats.value}  ·  {job.id}"
    return {
        "title": title,
        "url": job.url,
        "color": TIER_COLORS.get(job.tier, TIER_COLORS[3]),
        "description": description_text,
        "fields": fields,
        "footer": {"text": footer[:2048]},
    }


def _chunk(seq: list[Job], n: int) -> Iterable[list[Job]]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


async def post_jobs(client: httpx.AsyncClient, channel_id: str, jobs: list[Job]) -> dict[str, str]:
    """Post jobs to Discord, batched per company at up to 10 embeds per message.
    Returns a map of job.id -> message_id for jobs that successfully posted."""
    if not jobs:
        return {}

    by_company: dict[str, list[Job]] = {}
    for j in jobs:
        by_company.setdefault(j.company, []).append(j)

    # Tier order: lower tier number first
    ordered_companies = sorted(by_company.keys(), key=lambda c: (min(j.tier for j in by_company[c]), c.lower()))

    job_to_msg: dict[str, str] = {}
    url = f"{API_BASE}/channels/{channel_id}/messages"
    headers = _headers()

    for company in ordered_companies:
        for batch in _chunk(by_company[company], EMBEDS_PER_MESSAGE):
            payload = {"embeds": [_format_embed(j) for j in batch]}
            try:
                r = await client.post(url, headers=headers, json=payload, timeout=30.0)
                if r.status_code == 429:
                    # Honor Discord's retry hint then try once more
                    retry_after = float(r.json().get("retry_after", 1.0))
                    log.warning("discord 429 — sleeping %.2fs", retry_after)
                    await asyncio.sleep(retry_after + 0.1)
                    r = await client.post(url, headers=headers, json=payload, timeout=30.0)
                r.raise_for_status()
                msg = r.json()
                msg_id = str(msg.get("id", ""))
                for j in batch:
                    if msg_id:
                        job_to_msg[j.id] = msg_id
                log.info("discord posted %d embed(s) for %s (msg=%s)", len(batch), company, msg_id)
            except Exception as e:
                log.warning("discord post failed for %s: %s", company, e)
            await asyncio.sleep(0.2)  # spec §9 rate-limit cushion

    return job_to_msg


async def fetch_reactions(client: httpx.AsyncClient, channel_id: str, message_id: str, emoji: str) -> list[dict]:
    """Return the list of users who reacted with `emoji` on `message_id`. Empty list
    on missing/deleted messages or HTTP errors (treated as 'no reactions yet')."""
    # URL-encode the emoji
    from urllib.parse import quote
    encoded = quote(emoji, safe="")
    url = f"{API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}"
    try:
        r = await client.get(url, headers=_headers(), timeout=20.0)
        if r.status_code == 404:
            return []
        if r.status_code == 429:
            retry_after = float(r.json().get("retry_after", 1.0))
            await asyncio.sleep(retry_after + 0.1)
            r = await client.get(url, headers=_headers(), timeout=20.0)
        r.raise_for_status()
        return r.json() or []
    except Exception as e:
        log.warning("discord reaction fetch failed for msg=%s: %s", message_id, e)
        return []
