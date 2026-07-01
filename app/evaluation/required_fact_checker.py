from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass


_PUNCTUATION_PATTERN = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9#_.]+")
_SEGMENT_PATTERN = re.compile(r"[\n。！？；;]+")
_ATOMIC_SPLIT_PATTERN = re.compile(
    r"[，,；;、]|(?:以及|并且|同时|而且|还应|并应|且应|和|及|或)"
)
_SOURCE_PATTERN = re.compile(r"\[来源[^\]]+\]")
_SPECIAL_TOKEN_PATTERN = re.compile(
    r"16#[0-9a-f]+|0x[0-9a-f]+|[a-z]+(?:_[a-z0-9]+)+|\b(?:req|done|busy|error|status|connect|unitid|ip|tcp)\b|\d+(?:\.\d+)?",
    re.I,
)

_PHRASE_GROUPS = (
    (("需要检查", "需要核对", "应当检查", "应当核对", "应检查", "应核对", "应确认", "必须检查", "必须核对", "必须确认", "需检查", "需核对", "确认", "检查", "验证"), "核对"),
    (("正在运行", "运行状态", "处于运行状态"), "运行"),
    (("通信伙伴", "从站", "对端设备", "远端设备"), "对端"),
    (("没有收到响应", "未收到响应", "没有响应", "未响应"), "未响应"),
    (("从零开始", "从0开始", "零基"), "零基"),
    (("会产生", "常会产生", "可能导致", "会导致", "造成"), "导致"),
    (("调用时序", "调用节拍"), "调用时序"),
    (("网络可达", "网络可达性"), "网络可达"),
    (("不可以", "不可", "不能"), "不能"),
    (("不应该", "不应", "不要"), "不应"),
    (("功能安全评估", "功能安全评价"), "功能安全评估"),
    (("现场工程师", "现场有资质工程师", "有资质人员"), "现场有资质工程师"),
    (("参数错误", "参数异常"), "参数错误"),
    (("错误值", "数值错误"), "错误值"),
    (("读取长度", "请求长度", "数据长度"), "数据长度"),
    (("描述为", "定义为", "表示"), "表示"),
    (("是否匹配", "相匹配", "匹配"), "匹配"),
    (("连接描述错误", "连接描述无效", "连接描述不受支持"), "连接描述问题"),
    (("字节排列", "字节序排列", "字排列", "字序排列"), "字序"),
    (("不能因数值看起来接近", "不能只凭数值看起来接近"), "不能凭近似数值"),
    ((
        "modbus 不统一规定多个寄存器之间的字顺序",
        "modbus未规定跨寄存器的字顺序",
        "多寄存器数值的字顺序由设备实现决定",
    ), "多寄存器字顺序由设备决定"),
)

_GENERIC_PREFIXES = (
    "还需",
    "还应",
    "需要",
    "应当",
    "应",
    "必须",
    "同时",
    "并",
)


@dataclass(frozen=True)
class AtomicMatch:
    fact_part: str
    matched: bool
    method: str
    score: float
    matched_excerpt: str


@dataclass(frozen=True)
class RequiredFactDiagnosis:
    required_fact: str
    match_type: str
    classification: str
    exact_match: bool
    semantic_match: bool
    diagnostic_covered: bool
    checker_false_negative: bool
    gold_directly_supports: bool
    required_fact_too_broad: bool
    answer_atomic_matches: list[dict]
    gold_atomic_matches: list[dict]
    rationale: str

    def to_dict(self) -> dict:
        return asdict(self)


def _replace_phrases(value: str) -> str:
    result = value.lower()
    for variants, canonical in _PHRASE_GROUPS:
        for variant in sorted(variants, key=len, reverse=True):
            result = result.replace(variant.lower(), canonical)
    return result


def normalize_text(value: str) -> str:
    value = _SOURCE_PATTERN.sub("", value)
    return _PUNCTUATION_PATTERN.sub("", _replace_phrases(value))


def legacy_exact_match(answer: str, required_fact: str) -> bool:
    """Preserve the historical metric: lowercase + whitespace removal only."""
    normalize = lambda value: "".join(value.lower().split())
    return normalize(required_fact) in normalize(answer)


def _segments(value: str) -> list[str]:
    value = _SOURCE_PATTERN.sub("", value)
    return [segment.strip() for segment in _SEGMENT_PATTERN.split(value) if normalize_text(segment)]


def _atomic_parts(required_fact: str) -> list[str]:
    raw_parts = [part.strip() for part in _ATOMIC_SPLIT_PATTERN.split(required_fact) if part.strip()]
    parts: list[str] = []
    for part in raw_parts or [required_fact]:
        normalized = part
        for prefix in _GENERIC_PREFIXES:
            if normalized.startswith(prefix) and len(normalized) > len(prefix) + 1:
                normalized = normalized[len(prefix) :]
                break
        if len(normalize_text(normalized)) >= 2:
            parts.append(normalized)
    return parts or [required_fact]


def _bigrams(value: str) -> set[str]:
    value = normalize_text(value)
    return {value[index : index + 2] for index in range(max(0, len(value) - 1))}


def _similarity(left: str, right: str) -> float:
    left_normalized, right_normalized = normalize_text(left), normalize_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    sequence = difflib.SequenceMatcher(None, left_normalized, right_normalized).ratio()
    left_bigrams = _bigrams(left_normalized)
    bigram_recall = len(left_bigrams & _bigrams(right_normalized)) / max(1, len(left_bigrams))
    return max(sequence, bigram_recall)


def _special_tokens(value: str) -> set[str]:
    return {token.lower().replace(" ", "") for token in _SPECIAL_TOKEN_PATTERN.findall(value)}


def _match_atom(atom: str, text: str, *, threshold: float = 0.72) -> AtomicMatch:
    normalized_atom = normalize_text(atom)
    normalized_text = normalize_text(text)
    if normalized_atom and normalized_atom in normalized_text:
        return AtomicMatch(atom, True, "normalized_substring", 1.0, atom)

    required_tokens = _special_tokens(normalized_atom)
    text_tokens = _special_tokens(normalized_text)
    if required_tokens - text_tokens:
        return AtomicMatch(atom, False, "missing_required_identifier", 0.0, "")

    best_score = 0.0
    best_segment = ""
    for segment in _segments(text):
        score = _similarity(atom, segment)
        if score > best_score:
            best_score, best_segment = score, segment

    atom_length = len(normalized_atom)
    if atom_length <= 4:
        matched = normalized_atom in normalized_text
        method = "short_anchor_exact" if matched else "short_anchor_missing"
    else:
        atom_bigrams = _bigrams(normalized_atom)
        whole_recall = len(atom_bigrams & _bigrams(normalized_text)) / max(1, len(atom_bigrams))
        matched = best_score >= threshold or whole_recall >= min(0.78, threshold + 0.06)
        method = "segment_similarity" if best_score >= whole_recall else "distributed_atomic_coverage"
        best_score = max(best_score, whole_recall)
    return AtomicMatch(atom, matched, method, round(best_score, 4), best_segment[:240])


def _match_fact(
    required_fact: str,
    text: str,
    *,
    threshold: float = 0.72,
    minimum_atom_ratio: float = 1.0,
) -> tuple[bool, list[AtomicMatch]]:
    full_match = _match_atom(required_fact, text, threshold=threshold)
    matches = [_match_atom(atom, text, threshold=threshold) for atom in _atomic_parts(required_fact)]
    matched_ratio = sum(item.matched for item in matches) / max(1, len(matches))
    return full_match.matched or matched_ratio >= minimum_atom_ratio, matches


def diagnose_required_fact(
    required_fact: str,
    answer: str,
    gold_text: str,
) -> RequiredFactDiagnosis:
    exact = legacy_exact_match(answer, required_fact)
    narrative_answer = re.sub(
        r"4\. 引用来源.*?5\. 安全提示",
        "5. 安全提示",
        answer,
        flags=re.S,
    )
    semantic, answer_matches = _match_fact(
        required_fact, narrative_answer, threshold=0.70, minimum_atom_ratio=1.0
    )
    gold_supported, gold_matches = _match_fact(
        required_fact, gold_text, threshold=0.60, minimum_atom_ratio=0.60
    )
    too_broad = len(_atomic_parts(required_fact)) >= 3
    partial_answer = any(item.matched for item in answer_matches) and not semantic

    if not gold_supported:
        classification = "required_fact_not_directly_supported_by_gold"
        rationale = "required_fact 的至少一个原子事实无法在人工 gold 原文中直接匹配。"
    elif exact:
        classification = "exact_match"
        rationale = "命中历史 exact 口径。"
    elif semantic:
        classification = "checker_false_negative"
        rationale = "历史 exact checker 未命中，但确定性的规范化、同义短语或原子事实匹配已覆盖。"
    elif too_broad and partial_answer:
        classification = "required_fact_too_broad"
        rationale = "required_fact 包含多个原子事实，当前回答仅覆盖其中一部分。"
    else:
        classification = "missing_from_answer"
        rationale = "gold 直接支持该事实，但当前回答未达到保守的确定性语义匹配阈值。"

    diagnostic_covered = gold_supported and (exact or semantic)
    match_type = "exact_match" if exact else "semantic_match" if semantic else "no_match"
    return RequiredFactDiagnosis(
        required_fact=required_fact,
        match_type=match_type,
        classification=classification,
        exact_match=exact,
        semantic_match=semantic and not exact,
        diagnostic_covered=diagnostic_covered,
        checker_false_negative=classification == "checker_false_negative",
        gold_directly_supports=gold_supported,
        required_fact_too_broad=too_broad,
        answer_atomic_matches=[asdict(item) for item in answer_matches],
        gold_atomic_matches=[asdict(item) for item in gold_matches],
        rationale=rationale,
    )
