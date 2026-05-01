from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# Patterns deliberately allow an optional "visa" between the verb and "sponsor"
# so common phrasings like "do not provide visa sponsorship" match. The spec's
# original patterns missed that — caught in the filter unit checks.
NO_SPONSOR_PATTERNS = re.compile(
    r"("
    r"no\s+(visa\s+)?sponsorship|"
    r"unable\s+to\s+(provide\s+|offer\s+)?(visa\s+)?sponsor|"
    r"cannot\s+(provide\s+|offer\s+)?(visa\s+)?sponsor|"
    r"do\s+(not|n['']t)\s+(provide\s+|offer\s+)?(visa\s+)?sponsor|"
    r"does\s+(not|n['']t)\s+(provide\s+|offer\s+)?(visa\s+)?sponsor|"
    r"will\s+not\s+(provide\s+|offer\s+)?(visa\s+)?sponsor|"
    r"won['']t\s+(provide\s+|offer\s+)?(visa\s+)?sponsor|"
    r"without\s+(needing\s+|requiring\s+)?(visa\s+)?sponsorship|"
    r"without\s+the\s+need\s+for\s+sponsorship|"
    r"must\s+be\s+(legally\s+)?authorized\s+to\s+work\s+in\s+the\s+(us|united\s+states)\s+(without|on\s+a\s+permanent)|"
    r"u\.?s\.?\s+citizen(ship)?\s+(required|only)|"
    r"must\s+be\s+a\s+u\.?s\.?\s+citizen|"
    r"must\s+be\s+a\s+citizen|"
    r"permanent\s+resident\s+(required|status\s+required)|"
    r"\bitar\b|"
    r"security\s+clearance"
    r")",
    re.IGNORECASE,
)


# Within ~80 chars after a clearance/ITAR/citizenship phrase, these phrases mean
# "the requirement is optional" → don't reject.
_SOFTENING_NEARBY = re.compile(
    r"(not\s+required|not\s+necessary|nice\s+to\s+have|preferred\s+but\s+not|"
    r"plus\s+but\s+not|but\s+a\s+plus|but\s+not\s+required|optional|"
    r"if\s+applicable|where\s+applicable)",
    re.IGNORECASE,
)
_SOFTENABLE = ("security clearance", "itar")


def passes_sponsorship(description: str, *, job_title: str = "", company: str = "") -> bool:
    """Reject if any explicit no-sponsorship marker matches. Logs the matched substring
    so we can spot-check false positives in week 1 (per spec §7.4 callout)."""
    if not description:
        return True  # nothing to scan; don't reject on missing data
    text = description.lower()
    m = NO_SPONSOR_PATTERNS.search(text)
    if not m:
        return True

    matched = m.group().lower()
    if any(phrase in matched for phrase in _SOFTENABLE):
        # Look in the ±80-char window for "not required" / "but a plus" etc.
        window = text[max(0, m.start() - 80): m.end() + 80]
        if _SOFTENING_NEARBY.search(window):
            return True

    snippet = description[max(0, m.start() - 40): m.end() + 40].replace("\n", " ")
    log.info("sponsorship reject [%s] %s :: …%s…", company, job_title, snippet)
    return False
