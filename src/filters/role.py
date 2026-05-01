from __future__ import annotations

import re

ROLE_INCLUDE = re.compile(
    r"\b("
    r"machine\s+learning|"
    r"\bml\b|mle\b|\bml[-\s]?eng|"
    r"inference|"
    r"mlsys|ml[-\s]?sys(tems)?|"
    r"ai\s+infra|ml\s+infra|ai[-\s]?infrastructure|"
    r"\bgpu\b|\bcuda\b|"
    r"performance\s+engineer|perf\s+engineer|"
    r"compiler|kernel\s+engineer|"
    r"software\s+engineer|swe\b|"
    r"backend\s+engineer|"
    r"distributed\s+systems|distributed\s+training|"
    r"platform\s+engineer|systems\s+engineer|"
    r"member\s+of\s+technical\s+staff|mts\b|"
    r"research\s+engineer|"
    r"forward\s+deployed\s+engineer|fde\b|"
    r"model\s+(deployment|serving)|"
    r"ml\s+platform"
    r")\b",
    re.IGNORECASE,
)

ROLE_EXCLUDE = re.compile(
    r"\b("
    r"intern\b|internship|"
    r"product\s+manager|pm\b|"
    r"designer|design\s+lead|ux|ui\s+(designer|engineer)|"
    r"sales|account\s+executive|ae\b|"
    r"marketing|growth\s+marketer|content\s+marketer|"
    r"recruiter|talent|people\s+ops|"
    r"finance|accounting|legal|paralegal|"
    r"customer\s+success|customer\s+support|"
    r"executive\s+assistant|admin\b"
    r")\b",
    re.IGNORECASE,
)


def passes_role(title: str, *, extra_include: list[str] | None = None,
                extra_exclude: list[str] | None = None) -> bool:
    if not title:
        return False
    if ROLE_EXCLUDE.search(title):
        return False
    if extra_exclude:
        for pat in extra_exclude:
            if re.search(pat, title, re.IGNORECASE):
                return False
    if ROLE_INCLUDE.search(title):
        return True
    if extra_include:
        for pat in extra_include:
            if re.search(pat, title, re.IGNORECASE):
                return True
    return False
