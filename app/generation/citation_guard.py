from __future__ import annotations

import re

from app.models import SearchHit


CHUNK_ID_PATTERN = re.compile(r"\|\s*([^\]|]+)\]")
SOURCE_INDEX_PATTERN = re.compile(r"\[来源\s*(\d+)(?:[:：][^\]]*)?\]")


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
