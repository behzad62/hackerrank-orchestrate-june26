from __future__ import annotations

import re

INJECTION_PATTERNS = [
    re.compile(r"\bignore\s+(all\s+)?previous\s+instructions\b", re.IGNORECASE),
    re.compile(r"\bapprove\s+(this\s+)?claim\b", re.IGNORECASE),
    re.compile(r"\bmark\s+(this\s+row\s+)?supported\b", re.IGNORECASE),
    re.compile(r"\breturn\s+supported\b", re.IGNORECASE),
    re.compile(r"\bskip\s+(the\s+)?review\b", re.IGNORECASE),
    re.compile(r"\bfollow\s+it\s+and\s+approve\b", re.IGNORECASE),
]


def detect_prompt_injection_flags(user_claim: str) -> list[str]:
    text = user_claim or ""
    if any(pattern.search(text) for pattern in INJECTION_PATTERNS):
        return ["text_instruction_present", "manual_review_required"]
    return []


def merge_risk_flags(*groups: list[str]) -> list[str]:
    ordered: list[str] = []
    for group in groups:
        for flag in group:
            if not flag or flag == "none":
                continue
            if flag not in ordered:
                ordered.append(flag)
    return ordered or ["none"]
