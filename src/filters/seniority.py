from __future__ import annotations

import re

SENIORITY_EXCLUDE = re.compile(
    r"\b("
    r"senior|sr\.|"
    r"staff|principal|"
    r"\blead\b|tech\s+lead|"
    r"director|head\s+of|"
    r"manager|management|engineering\s+manager|em\b|"
    r"\bvp\b|vice\s+president|"
    r"chief|executive"
    r")\b",
    re.IGNORECASE,
)


SENIORITY_INCLUDE_HINTS = re.compile(
    r"\b("
    r"junior|jr\.|"
    r"entry[-\s]?level|"
    r"new\s+grad|new\s+graduate|"
    r"university\s+grad|"
    r"early\s+career|"
    r"associate|"
    r"\bI\b|\bII\b"
    r")\b",
    re.IGNORECASE,
)


_MTS_CARVEOUT = re.compile(r"member\s+of\s+technical\s+staff", re.IGNORECASE)


def passes_seniority(title: str) -> bool:
    """Reject explicit senior/staff/lead/etc. Accept everything else (most new-grad
    titles have no level word at all, e.g. 'Software Engineer', 'ML Engineer').

    Carve-out: 'Member of Technical Staff' contains 'Staff' but is not a senior role
    at OpenAI/Anthropic etc. (spec §15.9). Strip it before the seniority check."""
    if not title:
        return False
    cleaned = _MTS_CARVEOUT.sub("", title)
    if SENIORITY_EXCLUDE.search(cleaned):
        return False
    return True
