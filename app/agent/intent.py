from __future__ import annotations

import re
from typing import Literal, TypedDict

from app.safety import is_unsafe_operation_request


IntentName = Literal[
    "alarm_diagnosis",
    "parameter_lookup",
    "table_lookup",
    "cross_section_procedure",
    "version_resolution",
    "general_manual_search",
    "safety_risk",
    "out_of_scope",
]


class IntentResult(TypedDict):
    intent: IntentName
    confidence: float
    matched_keywords: list[str]
    reason: str


UNSUPPORTED_SCOPE_KEYWORDS = (
    "allen-bradley",
    "controllogix",
    "rockwell",
    "三菱",
    "fx5u",
    "欧姆龙",
    "施耐德",
    "schneider",
    "台达",
    "汇川",
    "abb",
)
ALARM_KEYWORDS = ("故障码", "状态码", "报错", "报码", "status", "error")
PARAMETER_KEYWORDS = (
    "参数",
    "范围",
    "参数范围",
    "上下限",
    "最大值",
    "最小值",
    "默认值",
    "允许范围",
    "端口",
    "寄存器地址",
    "波特率",
    "unit id",
    "mb_data_len",
    "rd_mb_data_len",
    "wr_mb_data_len",
)
TABLE_KEYWORDS = (
    "表格",
    "表中",
    "表头",
    "哪一行",
    "哪一列",
    "第几行",
    "第几列",
    "table",
    "column",
    "row",
)
CROSS_SECTION_KEYWORDS = (
    "跨章节",
    "排查流程",
    "排查步骤",
    "检查顺序",
    "完整流程",
    "按哪些层",
    "分层排查",
    "如何排查",
)
VERSION_KEYWORDS = (
    "版本不一致",
    "版本冲突",
    "版本差异",
    "适用版本",
    "哪个版本",
    "固件版本",
    "手册版本",
    "firmware version",
    "version conflict",
)
ALARM_CODE_PATTERN = re.compile(
    r"(?:16#|0x)[0-9a-f]{2,4}|"
    r"(?<![0-9a-z])(?=[0-9a-f]{4}(?![0-9a-z]))(?=[0-9a-f]*[a-f])[0-9a-f]{4}",
    re.I,
)


def _matched(text: str, keywords: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in lowered]


def _result(
    intent: IntentName,
    confidence: float,
    matched_keywords: list[str],
    reason: str,
) -> IntentResult:
    return {
        "intent": intent,
        "confidence": confidence,
        "matched_keywords": list(dict.fromkeys(matched_keywords)),
        "reason": reason,
    }


def classify_intent(
    question: str,
    *,
    model: str = "S7-1200",
    version: str = "",
) -> IntentResult:
    """Classify a request with deterministic rules for shadow-mode observation."""
    text = " ".join(value for value in (question.strip(), version.strip()) if value)
    if is_unsafe_operation_request(question):
        return _result(
            "safety_risk",
            0.99,
            ["unsafe_operation_request"],
            "现有安全规则检测到请求包含可执行的高风险操作",
        )

    scope_matches = _matched(text, UNSUPPORTED_SCOPE_KEYWORDS)
    normalized_model = re.sub(r"[\s_-]", "", model.lower())
    if normalized_model and "s71200" not in normalized_model:
        scope_matches.append(model)
    if scope_matches:
        return _result(
            "out_of_scope",
            0.99,
            scope_matches,
            "请求包含当前知识库范围外的厂商或设备型号",
        )

    alarm_matches = _matched(text, ALARM_KEYWORDS)
    alarm_codes = ALARM_CODE_PATTERN.findall(text)
    if alarm_matches or alarm_codes:
        return _result(
            "alarm_diagnosis",
            0.98 if alarm_codes else 0.92,
            [*alarm_matches, *alarm_codes],
            "检测到故障码、状态码或报错诊断意图",
        )

    table_matches = _matched(text, TABLE_KEYWORDS)
    if table_matches:
        return _result(
            "table_lookup",
            0.92,
            table_matches,
            "检测到表格、行列或表头定位意图",
        )

    version_matches = _matched(text, VERSION_KEYWORDS)
    if version_matches:
        return _result(
            "version_resolution",
            0.91,
            version_matches,
            "检测到固件、手册或配置版本核对意图",
        )

    parameter_matches = _matched(text, PARAMETER_KEYWORDS)
    if parameter_matches:
        return _result(
            "parameter_lookup",
            0.90,
            parameter_matches,
            "检测到参数范围、默认值或通信参数查询意图",
        )

    procedure_matches = _matched(text, CROSS_SECTION_KEYWORDS)
    if procedure_matches:
        return _result(
            "cross_section_procedure",
            0.88,
            procedure_matches,
            "检测到需要跨章节组织的流程或分层排查意图",
        )

    return _result(
        "general_manual_search",
        0.50,
        [],
        "未命中专用规则，回退为普通手册检索",
    )
