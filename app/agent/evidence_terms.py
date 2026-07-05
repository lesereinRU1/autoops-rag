from __future__ import annotations

import re


MEANINGFUL_SHORT_TERMS = frozenset({"ID", "IP", "DB"})
GENERIC_TERMS = frozenset(
    {
        "PLC",
        "MANUAL",
        "DEVICE",
        "EQUIPMENT",
        "PARAMETER",
        "FAULT",
        "ALARM",
        "ERROR",
        "S7",
        "S7-1200",
        "S7-1500",
        "1200",
        "1500",
        "手册",
        "参数",
        "故障",
        "报警",
        "设备",
        "装置",
    }
)
SINGLE_DIGIT_PATTERN = re.compile(r"^\d$")
ALARM_CODE_PATTERN = re.compile(r"^16#[0-9A-F]+$", re.I)
ASCII_TERM_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _canonical(term: str) -> str:
    value = re.sub(r"\s+", "", str(term).strip().strip("，。！？；：,!?;:()[]{}"))
    if ALARM_CODE_PATTERN.fullmatch(value):
        return value.upper()
    if ASCII_TERM_PATTERN.fullmatch(value):
        return value.upper()
    return value


def normalize_technical_terms(terms: list[str]) -> list[str]:
    """Canonicalize and de-duplicate extracted terms without external services."""
    normalized: list[str] = []
    seen: set[str] = set()
    for term in terms:
        value = _canonical(term)
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            normalized.append(value)
    return normalized


def is_generic_term(term: str) -> bool:
    value = _canonical(term)
    if not value:
        return True
    if value in MEANINGFUL_SHORT_TERMS or ALARM_CODE_PATTERN.fullmatch(value):
        return False
    if SINGLE_DIGIT_PATTERN.fullmatch(value):
        return True
    if value.upper() in GENERIC_TERMS or value in GENERIC_TERMS:
        return True
    if len(value) < 2:
        return True
    return False


def filter_retry_identifiers(terms: list[str]) -> list[str]:
    """Keep only discriminative terms suitable for deciding a retrieval retry."""
    return [term for term in normalize_technical_terms(terms) if not is_generic_term(term)]


def generic_terms_in_text(text: str) -> list[str]:
    """Extract auditable generic terms, including Chinese words absent from the code-token regex."""
    matches: list[str] = []
    for term in sorted(GENERIC_TERMS, key=lambda value: (-len(value), value)):
        if ASCII_TERM_PATTERN.fullmatch(term) or term.isdigit():
            pattern = rf"(?<![A-Za-z0-9_-]){re.escape(term)}(?![A-Za-z0-9_-])"
            if re.search(pattern, text, re.I):
                matches.append(term)
        elif term in text:
            matches.append(term)
    return normalize_technical_terms(matches)
