from __future__ import annotations

import re

from app.evaluation.models import TechnicalIdentifierEvaluation


FAULT_CODE_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:16#|0x)[0-9A-Fa-f]{2,8}(?![A-Za-z0-9])", re.I)
MODEL_PATTERN = re.compile(r"(?<![A-Za-z0-9])S7[-\s]?\d{3,4}(?:[-/]\d{3,4})?(?![A-Za-z0-9])", re.I)
VERSION_PATTERN = re.compile(r"(?<![A-Za-z0-9])V\d+(?:\.\d+)+(?![A-Za-z0-9])", re.I)
RANGE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(-?\d+(?:\.\d+)?)\s*(?:~|～|至|到|-|–|—)\s*"
    r"(-?\d+(?:\.\d+)?)(?:\s*(ms|s|V|A|mA|Hz|kHz|MHz|℃|°C|%|字节|位|秒|毫秒))?",
    re.I,
)
PARAMETER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+|"
    r"MB_CLIENT|MB_SERVER|CONNECT|STATUS|REQ|DONE|BUSY|ERROR|UNITID|"
    r"RemotePort|InterfaceID|Role)(?![A-Za-z0-9_])",
    re.I,
)
VALUE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.#-])-?\d+(?:\.\d+)?(?:\s*(?:ms|s|V|A|mA|Hz|kHz|MHz|℃|°C|%|字节|位|秒|毫秒))?"
    r"(?![A-Za-z0-9_.])",
    re.I,
)
UNIT_PATTERN = re.compile(r"(?<![A-Za-z])(?:ms|mA|kHz|MHz|Hz|°C|V|A|s)(?![A-Za-z])|℃|%|字节|毫秒|秒|位")


def _canonical(kind: str, value: str) -> str:
    compact = re.sub(r"\s+", "", value).strip("，,。；;")
    if kind == "fault_code":
        digits = re.sub(r"^(?:16#|0x)", "", compact, flags=re.I).upper()
        return f"HEX:{digits.lstrip('0') or '0'}"
    if kind in {"parameter", "model"}:
        return compact.upper().replace(" ", "")
    if kind == "unit":
        return compact.lower()
    return compact.lower().replace("～", "~").replace("至", "~").replace("到", "~").replace("–", "~").replace("—", "~")


def _overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and span[1] > start for start, end in occupied)


def extract_technical_identifiers(text: str) -> dict[str, list[str]]:
    """Conservatively extract exact technical values from required-fact text."""

    extracted: dict[str, list[str]] = {
        "fault_code": [],
        "parameter": [],
        "range": [],
        "value": [],
        "unit": [],
        "model": [],
    }
    occupied: list[tuple[int, int]] = []
    for kind, pattern in (
        ("fault_code", FAULT_CODE_PATTERN),
        ("model", MODEL_PATTERN),
        ("range", RANGE_PATTERN),
        ("parameter", PARAMETER_PATTERN),
        ("version", VERSION_PATTERN),
    ):
        for match in pattern.finditer(text):
            if kind in {"range", "parameter", "version"} and _overlaps(
                match.span(), occupied
            ):
                continue
            occupied.append(match.span())
            if kind != "version":
                extracted[kind].append(match.group(0))
    for match in VALUE_PATTERN.finditer(text):
        if not _overlaps(match.span(), occupied):
            extracted["value"].append(match.group(0))
    for match in UNIT_PATTERN.finditer(text):
        extracted["unit"].append(match.group(0))
    return {
        kind: list(dict.fromkeys(values))
        for kind, values in extracted.items()
        if values
    }


def evaluate_technical_identifiers(
    required_facts: list[str], answer: str
) -> TechnicalIdentifierEvaluation:
    expected: dict[str, list[str]] = {}
    for fact in required_facts:
        for kind, values in extract_technical_identifiers(fact).items():
            expected.setdefault(kind, []).extend(values)
    expected = {
        kind: list(dict.fromkeys(values))
        for kind, values in expected.items()
        if values
    }
    answer_values = extract_technical_identifiers(answer)
    answer_canonical = {
        kind: {_canonical(kind, value) for value in values}
        for kind, values in answer_values.items()
    }
    matched: dict[str, list[str]] = {}
    missing: dict[str, list[str]] = {}
    for kind, values in expected.items():
        for value in values:
            target = matched if _canonical(kind, value) in answer_canonical.get(kind, set()) else missing
            target.setdefault(kind, []).append(value)
    total = sum(len(values) for values in expected.values())
    hit = sum(len(values) for values in matched.values())
    return TechnicalIdentifierEvaluation(
        expected=expected,
        matched=matched,
        missing=missing,
        matched_count=hit,
        total_count=total,
        accuracy=round(hit / total, 4) if total else None,
    )
