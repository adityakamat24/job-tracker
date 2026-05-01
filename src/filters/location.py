from __future__ import annotations

import re

from ..utils import NON_US_BLOCKERS, US_CITIES, US_GENERIC, US_STATES

_US_DESC_HINT = re.compile(r"\b(united\s+states|\bus\b|\bu\.s\.|usa)\b", re.IGNORECASE)


_WORD = re.compile(r"[a-z\.]+", re.IGNORECASE)


def _tokens(s: str) -> list[str]:
    """Split a location string on common separators and lowercase each piece."""
    return [t.strip().lower() for t in re.split(r"[,/|;]| - | – ", s) if t.strip()]


def _has_whole_word(haystack: str, needle: str) -> bool:
    """True iff `needle` appears as a whole word/phrase in `haystack`. Avoids the
    classic substring trap where 2-letter state codes (or, ga, nd, mo, al) match
    inside foreign city names (London, Bangalore, Remote, Munich)."""
    return re.search(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", haystack, re.IGNORECASE) is not None


def passes_location(location: str, description: str = "",
                    extra_include: list[str] | None = None,
                    title: str = "") -> bool:
    if not location and title:
        # Some boards (e.g. Mistral on Ashby) leave locationName empty and encode
        # the city in the title ("Software Engineer, Backend (London)"). Peek at
        # the title for non-US blockers; if none found, stay lenient.
        title_lower = title.lower()
        for blocker in NON_US_BLOCKERS:
            if _has_whole_word(title_lower, blocker):
                return False
        return True

    if not location:
        # Empty location, no title hint — be lenient; let other filters decide.
        return True

    loc_lower = location.lower().strip()
    extras = {e.lower() for e in (extra_include or [])}
    pool = US_GENERIC | US_STATES | US_CITIES | extras

    # Whole-string or whole-word match against the US pool
    if loc_lower in pool:
        return True
    for hub in pool:
        if _has_whole_word(loc_lower, hub):
            return True

    # Non-US blocker check BEFORE the remote+description fallback — otherwise
    # "Toronto, CAN-Remote" passes when the description happens to mention the US.
    for blocker in NON_US_BLOCKERS:
        if _has_whole_word(loc_lower, blocker):
            return False

    # Generic remote without geo qualifier — peek at description for US markers
    if _has_whole_word(loc_lower, "remote") or "remote" in loc_lower:
        if _US_DESC_HINT.search(description):
            return True
        return False

    # Loose default: better false-positive than false-negative
    return True
