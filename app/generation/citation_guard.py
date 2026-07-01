from __future__ import annotations

import re

from app.models import SearchHit


CHUNK_ID_PATTERN = re.compile(r"\|\s*([^\]|]+)\]")
SOURCE_INDEX_PATTERN = re.compile(r"\[来源\s*(\d+)(?:[:：][^\]]*)?\]")
NARRATIVE_PATTERN = re.compile(r"1\. 结论(.*?)4\. 引用来源", re.S)
MB_IDENTIFIER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])MB_[A-Z0-9_]+(?![A-Za-z0-9_])", re.I)
GENERALIZATION_TERMS = ("通常", "一般", "可能", "默认", "建议直接", "应该是")


def grounded_claims(answer: str) -> list[str]:
    """Return atomic claims from sections 1-3; the source manifest is excluded."""
    match = NARRATIVE_PATTERN.search(answer)
    if not match:
        return []
    narrative = re.sub(
        r"(?:^|\n)\s*[123]\.\s*(?:结论|原因|排查\s*/\s*换算建议)\s*",
        "\n",
        match.group(1),
    )
    claims: list[str] = []
    for part in re.split(r"(?<=[。！？；;])\s*(?!\[来源)|\n+", narrative):
        value = part.strip(" -•\t")
        plain = SOURCE_INDEX_PATTERN.sub("", value).strip(" 。；;\t")
        if len(plain) >= 3:
            claims.append(value)
    return claims


def validate_grounded_citations(
    answer: str, evidence: list[SearchHit]
) -> tuple[bool, list[str]]:
    """Require one precise, adjacent source citation for every factual claim."""
    warnings: list[str] = []
    claims = grounded_claims(answer)
    if not claims:
        return False, ["回答的结论、原因和排查建议中没有可校验的事实句。"]
    for position, claim in enumerate(claims, start=1):
        indexes = [int(value) for value in SOURCE_INDEX_PATTERN.findall(claim)]
        valid = [index for index in indexes if 1 <= index <= len(evidence)]
        if not indexes:
            warnings.append(f"第{position}条事实句没有来源编号。")
            continue
        if len(set(valid)) != 1 or len(indexes) != 1:
            warnings.append(f"第{position}条事实句必须且只能引用一个有效来源。")
        if not re.search(r"\[来源\s*\d+(?:[:：][^\]]*)?\]\s*[。！？；;]?$", claim):
            warnings.append(f"第{position}条事实句的来源编号必须紧邻句末。")
        if len(set(valid)) == 1 and len(indexes) == 1:
            source_text = evidence[valid[0] - 1].chunk.text
            plain_claim = SOURCE_INDEX_PATTERN.sub("", claim)
            missing_identifiers = sorted({
                value for value in MB_IDENTIFIER_PATTERN.findall(plain_claim)
                if value.lower() not in source_text.lower()
            })
            if missing_identifiers:
                warnings.append(
                    f"第{position}条事实句含引用来源未直接出现的标识："
                    + "、".join(missing_identifiers)
                    + "；请删去标识并只改写来源原文。"
                )
            unsupported_terms = [
                term for term in GENERALIZATION_TERMS
                if term in plain_claim and term not in source_text
            ]
            if unsupported_terms:
                warnings.append(
                    f"第{position}条事实句含引用来源未直接出现的扩展性措辞："
                    + "、".join(unsupported_terms)
                    + "；请改写为来源中的直接表述。"
                )
    return not warnings, warnings


def validate_citations(answer: str, evidence: list[SearchHit]) -> tuple[bool, list[str]]:
    allowed = {hit.chunk.chunk_id for hit in evidence}
    cited = set(CHUNK_ID_PATTERN.findall(answer))
    source_indexes = {int(value) for value in SOURCE_INDEX_PATTERN.findall(answer)}
    warnings: list[str] = []
    unknown = cited - allowed
    if unknown:
        warnings.append(f"回答包含未知引用：{', '.join(sorted(unknown))}")
    invalid_indexes = {index for index in source_indexes if index < 1 or index > len(evidence)}
    if invalid_indexes:
        warnings.append(f"回答包含无效来源编号：{', '.join(map(str, sorted(invalid_indexes)))}")
    if evidence and not cited and not source_indexes:
        warnings.append("回答没有可程序校验的来源引用。")
    return not warnings, warnings
