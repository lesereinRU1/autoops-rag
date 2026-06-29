from __future__ import annotations

import re


DOMAIN_TERMS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("通信角色", "客户端", "服务器"), ("client", "server", "role")),
    (("默认值", "缺省值"), ("default",)),
    (("允许", "范围", "最多", "最少"), ("permitted values", "range")),
    (("多少个寄存器", "寄存器数量"), ("number of registers", "quantity")),
    (("读取", "读保持寄存器"), ("read", "holding registers")),
    (("写入", "写保持寄存器"), ("write", "holding registers")),
    (("功能码",), ("function code", "Modbus function")),
    (("对应", "表示什么", "含义"), ("description", "meaning")),
    (("协议错误", "状态码"), ("protocol errors", "STATUS")),
    (("响应超时", "未响应"), ("no response", "assigned time", "server")),
)
TECHNICAL_TERM_PATTERN = re.compile(
    r"16#[0-9A-Fa-f]+|[A-Za-z]+_[A-Za-z0-9_]+|[A-Z][A-Z0-9]{2,}|[A-Z]?[a-z]+(?:[A-Z][A-Za-z0-9]+)+|\d+(?:,\d+)*(?:\.\d+)?",
)


def technical_terms(text: str) -> set[str]:
    return {value.lower().replace(" ", "") for value in TECHNICAL_TERM_PATTERN.findall(text)}


def expand_query(query: str) -> tuple[str, list[str]]:
    """Add a small audited Chinese-English domain dictionary without an LLM."""
    lowered = query.lower()
    additions: list[str] = []
    for triggers, terms in DOMAIN_TERMS:
        if any(trigger.lower() in lowered for trigger in triggers):
            for term in terms:
                if term.lower() not in lowered and term not in additions:
                    additions.append(term)

    # Normalize a bare four-digit hexadecimal status when the question identifies it as a status/code.
    if any(marker in lowered for marker in ("状态码", "故障码", "status", "error")):
        for value in re.findall(r"(?<![0-9a-f])([0-9a-f]{4})(?![0-9a-f])", lowered, re.I):
            normalized = f"16#{value.upper()}"
            if normalized.lower() not in lowered and normalized not in additions:
                additions.append(normalized)
    return " ".join([query, *additions]).strip(), additions
