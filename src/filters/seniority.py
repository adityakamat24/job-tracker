from __future__ import annotations

import re

SENIORITY_EXCLUDE = re.compile(
    r"\b("
    r"senior|sr|"  # bare 'sr' — matches 'Sr.', 'Sr ', 'SR' alike (the trailing \b
                   # in this regex matches after 'r' regardless of period). The
                   # earlier `sr\.` failed when followed by space because both `.`
                   # and ` ` are non-word chars, leaving no word boundary.
    r"staff|principal|"
    r"\blead\b|tech\s+lead|"
    r"director|head\s+of|"
    r"manager|management|engineering\s+manager|em\b|"
    r"\bvp\b|vice\s+president|"
    r"chief|executive|"
    r"distinguished|fellow"   # rare but real top-IC ladders (Walmart, MSFT, Sun)
    r")\b",
    re.IGNORECASE,
)

# Numbered seniority levels — title like "Machine Learning Engineer 4",
# "Software Engineer III", "MLE 5", "SDE III", "L5 Backend Engineer".
# Levels 3+ in arabic OR roman OR L-prefix are senior. Levels 1-2 stay
# acceptable (most new-grad numbered roles are "Engineer 1" / "Engineer II").
# spec §15.8 specifically calls this out for III.
NUMBERED_LEVEL_EXCLUDE = re.compile(
    r"\b("
    r"(?:engineer|scientist|developer|architect|swe|sde|mle|sre|researcher|analyst)"
    r"\s*"
    r"(?:I{3,}|IV|VI{0,3}|IX|X)\b"   # roman: III, IV, V, VI, VII, VIII, IX, X
    r"|"
    r"(?:engineer|scientist|developer|architect|swe|sde|mle|sre|researcher|analyst)"
    r"\s*"
    r"[3-9]\b"                          # arabic: Engineer 3..9
    r"|"
    r"\bL[3-9]\b|\bL1[0-9]\b"          # L3..L19 (Google/Meta-style)
    r")",
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
    if NUMBERED_LEVEL_EXCLUDE.search(cleaned):
        return False
    return True
