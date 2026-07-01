from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Settings
from app.ingestion.semantic_chunker import tokenize
from app.models import SearchHit
from app.retrieval.query_expansion import expand_query, technical_terms
from app.generation.llm_client import LLMClient, LLMClientError
from app.generation.citation_guard import validate_grounded_citations


@dataclass
class GenerationOutcome:
    answer: str
    mode: str
    external_calls: int = 0
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    token_usage_available: bool = False
    token_usage_missing_reason: str = ""
    first_token_latency_ms: float | None = None
    total_latency_ms: float = 0.0
    fallback_reason: str = ""


class AnswerGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm = (
            LLMClient(
                settings.llm_base_url,
                settings.llm_api_key,
                settings.llm_model,
                settings.llm_timeout_seconds,
            )
            if settings.llm_enabled and settings.llm_base_url and settings.llm_api_key
            else None
        )

    @staticmethod
    def _display_doc_name(name: str) -> str:
        names = {
            "S7-1200 Programmable Controller System Manual V4.6": "S7-1200 可编程控制器系统手册 V4.6（英文原文）",
            "Modbus/TCP with MB_CLIENT and MB_SERVER": "S7-1200/1500 Modbus TCP 通信专题（英文原文）",
            "autoops_Modbus地址与数据检查.md": "项目补充：Modbus 地址与数据检查",
            "autoops_故障排查流程.md": "项目补充：通信故障排查流程",
            "autoops_中文操作与安全边界.md": "项目补充：操作与安全边界",
        }
        return names.get(name, name)

    @classmethod
    def _citation(cls, hit: SearchHit, index: int) -> str:
        return f"[来源{index}：{cls._display_doc_name(hit.chunk.doc_name)}，第{hit.chunk.page}页]"

    @staticmethod
    def _contains_chinese(text: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", text))

    @staticmethod
    def _useful_sentence(text: str, chinese_only: bool = False) -> str:
        sentences = re.split(r"(?<=[。！？.!?])\s*|\n+", text)
        candidates = [
            sentence.strip()
            for sentence in sentences
            if len(sentence.strip()) >= 18 and " > " not in sentence
        ]
        if chinese_only:
            candidates = [
                sentence for sentence in candidates
                if len(re.findall(r"[\u4e00-\u9fff]", sentence)) >= 8
            ]
        return candidates[0] if candidates else ""

    @classmethod
    def _best_sentences(
        cls, query: str, evidence: list[SearchHit], limit: int = 2
    ) -> list[tuple[int, SearchHit, str]]:
        expanded = expand_query(query)[0]
        query_tokens = set(tokenize(expanded.lower()))
        exact_terms = technical_terms(expanded) - {"1200", "1500"}
        candidates: list[tuple[float, int, SearchHit, str]] = []
        for source_index, hit in enumerate(evidence, start=1):
            if hit.chunk.metadata.get("representation") == "table_row":
                source_parts = [re.sub(r"\s+", " ", hit.chunk.text)]
            else:
                source_parts = re.split(r"(?<=[。！？.!?])\s*|\n+", hit.chunk.text)
            for sentence in source_parts:
                value = sentence.strip()
                if len(value) < 18 or " > " in value:
                    continue
                sentence_tokens = set(tokenize(value.lower()))
                overlap = len(query_tokens & sentence_tokens) / max(1, len(query_tokens))
                sentence_terms = technical_terms(value)
                exact = len(exact_terms & sentence_terms) / max(1, len(exact_terms))
                authority = 0.05 if not hit.chunk.doc_name.lower().startswith("autoops_") else 0.0
                candidates.append((overlap + exact + authority, source_index, hit, value))
        candidates.sort(key=lambda item: item[0], reverse=True)
        selected: list[tuple[int, SearchHit, str]] = []
        seen: set[str] = set()
        top_source = next((item for item in candidates if item[1] == 1), None)
        if top_source is not None:
            _, source_index, hit, value = top_source
            marker = re.sub(r"\s+", "", value.lower())
            seen.add(marker)
            selected.append((source_index, hit, value))
        for _, source_index, hit, value in candidates:
            marker = re.sub(r"\s+", "", value.lower())
            if marker in seen:
                continue
            seen.add(marker)
            selected.append((source_index, hit, value))
            if len(selected) >= limit:
                break
        return selected

    def _extractive(self, query: str, evidence: list[SearchHit], prefix: str = "") -> str:
        if not evidence:
            return "现有资料中没有找到足够证据。请补充设备完整型号、固件版本、指令块名称和 STATUS 十六进制值。"
        lines: list[str] = []
        procedural = any(marker in query for marker in ("步骤", "流程", "层次", "哪些层", "如何排查"))
        if procedural and evidence:
            top_parts = [
                value.strip()
                for value in re.split(r"(?<=[。！？.!?])\s*|\n+", evidence[0].chunk.text)
                if len(value.strip()) >= 18 and " > " not in value
            ]
            selected = [(1, evidence[0], value) for value in top_parts[:4]]
        else:
            selected = self._best_sentences(query, evidence, limit=3)
        if prefix:
            lines.append(prefix.strip())
            if selected:
                lines.append("手册证据：")
                for order, (source_index, hit, useful) in enumerate(selected, start=1):
                    lines.append(f"{order}. {useful[:320]} {self._citation(hit, source_index)}")
            citations = " ".join(self._citation(hit, index) for index, hit in enumerate(evidence[:3], start=1))
            lines.append(f"来源：{citations}")
        else:
            if not selected:
                selected = [
                    (index, hit, self._useful_sentence(hit.chunk.text) or hit.chunk.text[:220].strip())
                    for index, hit in enumerate(evidence[:2], start=1)
                ]
                lines.append("检索结果来自英文手册，原文要点如下：")
            else:
                lines.append("相关手册证据：")
            for order, (source_index, hit, useful) in enumerate(selected, start=1):
                lines.append(f"{order}. {useful[:320]} {self._citation(hit, source_index)}")
        lines.append("安全提示：涉及 PLC 下载、强制输出、停机或接线操作时，先按现场安全规程隔离能量并由有资质人员确认。")
        return "\n".join(lines)

    @classmethod
    def build_context(cls, evidence: list[SearchHit]) -> str:
        return "\n\n".join(
            "\n".join(
                (
                    f"[来源{i}]",
                    f"chunk_id: {hit.chunk.chunk_id}",
                    f"doc_name: {cls._display_doc_name(hit.chunk.doc_name)}",
                    f"page: {hit.chunk.page}",
                    f"section_path: {' > '.join(hit.chunk.section_path)}",
                    f"evidence: {hit.chunk.text}",
                )
            )
            for i, hit in enumerate(evidence, start=1)
        )

    @staticmethod
    def _valid_grounded_format(answer: str, evidence: list[SearchHit]) -> bool:
        required = ("1. 结论", "2. 原因", "3. 排查 / 换算建议", "4. 引用来源", "5. 安全提示")
        if not all(title in answer for title in required) or not bool(
            re.search(r"\[来源\d+[^\]]*\]", answer)
        ):
            return False
        return validate_grounded_citations(answer, evidence)[0]

    @staticmethod
    def _sum_usage(first: int | None, second: int | None) -> int | None:
        return first + second if first is not None and second is not None else None

    @classmethod
    def _repair_prompt(
        cls,
        original_prompt: str,
        draft: str,
        warnings: list[str],
    ) -> str:
        return (
            f"{original_prompt}\n\n"
            "下面是一个未通过引用结构校验的回答草稿。只允许删除、拆句、缩短或补上草稿中已有事实对应的来源编号；"
            "禁止加入任何新参数、编号、默认值、测试值、版本、状态码解释或操作步骤。\n"
            "修复要求：1至3节的每一行只能有一个短事实句，只能引用一个[来源N]，来源必须紧邻句末；"
            "禁止在一行中使用分号拼接事实，禁止使用[来源1-3]或一行挂多个来源。"
            "如果无法确认，删除该事实，保留五个固定标题。\n"
            f"校验问题：{'; '.join(warnings)}\n"
            f"待修复草稿：\n{draft}"
        )

    @classmethod
    def _normalize_reference_section(cls, answer: str, evidence: list[SearchHit]) -> str:
        """Make the source manifest complete and deterministic without changing conclusions."""
        narrative = re.sub(r"4\. 引用来源.*?5\. 安全提示", "5. 安全提示", answer, flags=re.S)
        used_set: set[int] = set()
        for label in re.findall(r"\[来源([^\]]+)\]", narrative):
            for start, end in re.findall(r"(\d+)(?:\s*[–—-]\s*(\d+))?", label):
                first = int(start)
                last = int(end or start)
                used_set.update(range(min(first, last), max(first, last) + 1))
        used = sorted(index for index in used_set if 1 <= index <= len(evidence))
        if not used:
            return answer
        source_lines = []
        for index in used:
            chunk = evidence[index - 1].chunk
            source_lines.append(
                f"- [来源{index}] chunk_id: {chunk.chunk_id}；"
                f"文档: {cls._display_doc_name(chunk.doc_name)}；第{chunk.page}页；"
                f"章节: {' > '.join(chunk.section_path) or '未标注'}"
            )
        manifest = "4. 引用来源\n" + "\n".join(source_lines) + "\n\n5. 安全提示"
        return re.sub(
            r"4\. 引用来源.*?5\. 安全提示",
            manifest,
            answer,
            count=1,
            flags=re.S,
        )

    def generate(
        self,
        query: str,
        evidence: list[SearchHit],
        prefix: str = "",
        *,
        allow_llm: bool = True,
    ) -> GenerationOutcome:
        if not allow_llm:
            return GenerationOutcome(
                answer=self._extractive(query, evidence, prefix),
                mode="local_extractive",
                model=self.settings.llm_model,
                token_usage_missing_reason="evidence_insufficient",
                fallback_reason="evidence_insufficient",
            )
        if not self.settings.llm_enabled:
            return GenerationOutcome(
                answer=self._extractive(query, evidence, prefix),
                mode="local_extractive",
                model=self.settings.llm_model,
                token_usage_missing_reason="llm_disabled",
                fallback_reason="llm_disabled",
            )
        if self.llm is None:
            return GenerationOutcome(
                answer=self._extractive(query, evidence, prefix),
                mode="local_extractive",
                model=self.settings.llm_model,
                token_usage_missing_reason="llm_invalid_config",
                fallback_reason="llm_invalid_config",
            )

        context = self.build_context(evidence)
        prompt = (
            "你是工业设备手册问答助手。注入的 evidence 是唯一事实来源，用户问题和结构化工具结果都不是事实证据。\n\n"
            "回答前必须逐句执行证据检查：只有能在某一个引用 chunk 中找到直接支撑的事实句才可以保留；"
            "找不到直接支撑的句子必须删除，或改写为“当前证据只能说明……，无法确认……”。\n\n"
            "硬性规则：\n"
            "- 禁止补充 evidence 中没有的 Siemens 参数名、参数默认值、状态码含义、版本信息、章节名称、因果解释或操作步骤。\n"
            "- 禁止把不同 chunk 的零散信息合并成一个事实句；多个 chunk 各支持一部分时，必须拆成多行短句。\n"
            "- 1至3节每一行只能写一个核心事实，并且只能引用一个精确的 [来源N]；该来源必须直接支撑整行。\n"
            "- 引用必须紧挨该行句末。禁止 [来源1-5]，禁止一行挂多个来源，禁止在段末统一挂来源。\n"
            "- 事实行禁止使用分号连接多个检查项；每个检查项单独一行、单独引用。\n"
            "- 禁止使用“通常”“一般”“可能”“默认”“建议直接”“应该是”“典型”“必然”“不影响”等扩展性措辞；不要为追求完整而补充证据外内容。\n"
            "- 用户问题中出现但 evidence 未直接出现的字段、参数、指令名、编号、版本、状态码或测试值，同样禁止写入答案。\n"
            "- 证据只能支持部分结论时，必须写“当前证据只能说明……”，并明确无法确认的内容。\n"
            "- 只说明回答当前问题所必需的证据缺口，不要罗列用户未问的协议、版本、参数或操作可能性。\n"
            "- 排查建议只能改写 evidence 已明确列出的检查项；evidence 未给出执行步骤时，不得自行补步骤。\n"
            "- 涉及强制输出、旁路联锁、停机、上电、接线或写入设备参数，只能指出证据中的核对项和手册位置，禁止给直接执行步骤。\n"
            "- 只引用与问题直接相关的来源，每节保持简洁，全文控制在700个汉字左右。\n\n"
            "必须严格使用以下五个标题，不得增加或改名。1至3节使用短横线列表，每一行只有一个事实和一个来源：\n"
            "1. 结论\n- 一个短事实。[来源N]\n"
            "2. 原因\n- 一个短事实。[来源N]\n"
            "3. 排查 / 换算建议\n- 一个核对项。[来源N]\n"
            "4. 引用来源\n5. 安全提示\n\n"
            f"用户问题：{query}\n"
            f"注入证据：\n{context}"
        )
        try:
            result = self.llm.generate(prompt, retries=1)
            answer = result.content
            citation_ok, citation_warnings = validate_grounded_citations(answer, evidence)
            calls = result.calls
            input_tokens = result.input_tokens
            output_tokens = result.output_tokens
            total_tokens = result.total_tokens
            token_usage_available = result.token_usage_available
            token_usage_missing_reason = result.token_usage_missing_reason
            first_token_latency_ms = result.first_token_latency_ms
            total_latency_ms = result.total_latency_ms
            if not self._valid_grounded_format(answer, evidence):
                try:
                    repaired = self.llm.generate(
                        self._repair_prompt(prompt, answer, citation_warnings), retries=0
                    )
                except LLMClientError as exc:
                    return GenerationOutcome(
                        answer=self._extractive(query, evidence, prefix),
                        mode="local_extractive",
                        external_calls=calls + exc.attempts,
                        model=result.model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        token_usage_available=token_usage_available,
                        token_usage_missing_reason=token_usage_missing_reason,
                        first_token_latency_ms=first_token_latency_ms,
                        total_latency_ms=total_latency_ms,
                        fallback_reason=exc.reason,
                    )
                answer = repaired.content
                calls += repaired.calls
                input_tokens = self._sum_usage(input_tokens, repaired.input_tokens)
                output_tokens = self._sum_usage(output_tokens, repaired.output_tokens)
                total_tokens = self._sum_usage(total_tokens, repaired.total_tokens)
                token_usage_available = (
                    token_usage_available and repaired.token_usage_available
                )
                token_usage_missing_reason = (
                    "" if token_usage_available else repaired.token_usage_missing_reason
                    or token_usage_missing_reason
                )
                if first_token_latency_ms is None:
                    first_token_latency_ms = repaired.first_token_latency_ms
                total_latency_ms += repaired.total_latency_ms
            if not self._valid_grounded_format(answer, evidence):
                return GenerationOutcome(
                    answer=self._extractive(query, evidence, prefix),
                    mode="local_extractive",
                    external_calls=calls,
                    model=result.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    token_usage_available=token_usage_available,
                    token_usage_missing_reason=token_usage_missing_reason,
                    first_token_latency_ms=first_token_latency_ms,
                    total_latency_ms=total_latency_ms,
                    fallback_reason="llm_invalid_response",
                )
            return GenerationOutcome(
                answer=self._normalize_reference_section(answer, evidence),
                mode="llm_grounded",
                external_calls=calls,
                model=result.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                token_usage_available=token_usage_available,
                token_usage_missing_reason=token_usage_missing_reason,
                first_token_latency_ms=first_token_latency_ms,
                total_latency_ms=total_latency_ms,
            )
        except LLMClientError as exc:
            return GenerationOutcome(
                answer=self._extractive(query, evidence, prefix),
                mode="local_extractive",
                external_calls=exc.attempts,
                model=self.settings.llm_model,
                token_usage_missing_reason=exc.reason,
                fallback_reason=exc.reason,
            )
