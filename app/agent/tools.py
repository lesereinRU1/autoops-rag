from __future__ import annotations

import json
import re
import time
from typing import Any

from app.agent.memory import MemoryStore
from app.models import ToolResult


FAULT_CODE_PATTERN = re.compile(r"(?:16#|0x)?([0-9A-Fa-f]{4})", re.I)
VERSION_PATTERN = re.compile(r"(?<![A-Za-z0-9])V?\d+(?:\.\d+)+", re.I)
TECHNICAL_TERM_PATTERN = re.compile(
    r"16#[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9_#.-]+|\d+(?:\.\d+)+"
)
TABLE_NAMES = ("manual_table_rows", "table_rows")
TABLE_COLUMNS = (
    "chunk_id",
    "source",
    "doc_name",
    "page",
    "section",
    "section_path",
    "table_id",
    "row_id",
    "row_index",
    "headers",
    "header",
    "parameter_name",
    "text",
    "content",
    "row_text",
    "model",
    "version",
)
SEARCHABLE_TABLE_COLUMNS = (
    "headers",
    "header",
    "parameter_name",
    "text",
    "content",
    "row_text",
    "source",
    "doc_name",
    "section",
    "section_path",
    "table_id",
)
PROVENANCE_FIELDS = (
    "chunk_id",
    "source",
    "doc_name",
    "page",
    "section",
    "section_path",
    "table_id",
    "row_id",
    "row_index",
)


def format_alarm(record: dict | None) -> str:
    if not record:
        return "结构化故障码库中未找到该代码，将改用手册检索。"
    causes = json.loads(record["causes"]) if record.get("causes", "").startswith("[") else [record.get("causes", "")]
    checks = json.loads(record["checks"]) if record.get("checks", "").startswith("[") else [record.get("checks", "")]
    return (
        f"故障码 {record['code']}：{record['title']}。{record['meaning']}\n"
        f"可能原因：{'；'.join(filter(None, causes))}\n"
        f"建议核对：{'；'.join(filter(None, checks))}\n"
        f"结构化来源：{record.get('source', '')}"
    )


def format_parameter(record: dict | None, value: float | None = None) -> str:
    if not record:
        return "结构化参数库中未找到该参数，将改用手册检索。"
    def display_number(number) -> str:
        value_number = float(number)
        return str(int(value_number)) if value_number.is_integer() else str(value_number)

    minimum = display_number(record["minimum"])
    maximum = display_number(record["maximum"])
    result = f"参数 {record['name']}：允许范围 {minimum}到{maximum} {record['unit']}。{record['notes']}"
    if value is not None:
        inside = record["minimum"] <= value <= record["maximum"]
        result += f" 当前值 {value} {record['unit']} {'在' if inside else '不在'}该演示数据范围内。"
    result += f" 结构化来源：{record['source']}"
    return result


def format_verified_solution(record: dict | None) -> str:
    if not record:
        return ""
    return (
        f"已找到经用户确认的历史方案（方案ID {record['id']}，相似度 {record['similarity']}）：\n"
        f"历史问题：{record['problem']}\n"
        f"已验证方案：{record['solution']}\n"
        "该方案只作为优先参考，仍需核对本次设备型号、固件版本和原始手册证据。"
    )


def _elapsed_ms(started: float) -> float:
    return max((time.perf_counter() - started) * 1000, 0.001)


def _provenance(record: dict[str, Any]) -> dict[str, Any]:
    return {
        field: record[field]
        for field in PROVENANCE_FIELDS
        if field in record and record[field] not in (None, "", [])
    }


def _search_terms(query: str) -> list[str]:
    values = [query.strip(), *TECHNICAL_TERM_PATTERN.findall(query)]
    return list(dict.fromkeys(value.lower() for value in values if value.strip()))


class SQLiteToolbox:
    """Read-only tool adapters over the existing MemoryStore query methods."""

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def lookup_fault_code(
        self, query: str, model: str | None = None
    ) -> ToolResult:
        started = time.perf_counter()
        match = FAULT_CODE_PATTERN.search(query or "")
        code = match.group(1) if match else (query or "").strip()
        try:
            record = self.memory.lookup_alarm(code, model or "S7-1200") if code else None
        except Exception as exc:
            return ToolResult(
                tool="lookup_fault_code",
                success=False,
                latency_ms=_elapsed_ms(started),
                error="sqlite_query_failed",
                metadata={"found": False, "error_type": type(exc).__name__},
            )
        if not record:
            return ToolResult(
                tool="lookup_fault_code",
                success=True,
                content="未找到匹配的故障码记录。",
                latency_ms=_elapsed_ms(started),
                metadata={"found": False, "query_code": code},
            )
        provenance = _provenance(record)
        return ToolResult(
            tool="lookup_fault_code",
            success=True,
            content=format_alarm(record),
            provenance=[provenance] if provenance else [],
            latency_ms=_elapsed_ms(started),
            metadata={
                "found": True,
                "code": record.get("code", ""),
                "model": record.get("model", ""),
                "citeable_evidence": False,
            },
        )

    def lookup_parameter(
        self, query: str, model: str | None = None
    ) -> ToolResult:
        started = time.perf_counter()
        normalized_model = model or "S7-1200"
        try:
            record = (
                self.memory.find_parameter_in_text(query or "", normalized_model)
                if (query or "").strip()
                else None
            )
            if record is None and (query or "").strip():
                record = self.memory.lookup_parameter(query.strip(), normalized_model)
        except Exception as exc:
            return ToolResult(
                tool="lookup_parameter",
                success=False,
                latency_ms=_elapsed_ms(started),
                error="sqlite_query_failed",
                metadata={"found": False, "error_type": type(exc).__name__},
            )
        if not record:
            return ToolResult(
                tool="lookup_parameter",
                success=True,
                content="未找到匹配的参数记录。",
                latency_ms=_elapsed_ms(started),
                metadata={"found": False},
            )
        provenance = _provenance(record)
        return ToolResult(
            tool="lookup_parameter",
            success=True,
            content=format_parameter(record),
            provenance=[provenance] if provenance else [],
            latency_ms=_elapsed_ms(started),
            metadata={
                "found": True,
                "name": record.get("name", ""),
                "minimum": record.get("minimum"),
                "maximum": record.get("maximum"),
                "unit": record.get("unit", ""),
                "model": record.get("model", ""),
                "citeable_evidence": False,
            },
        )

    def lookup_table_rows(
        self,
        query: str,
        model: str | None = None,
        limit: int = 5,
    ) -> ToolResult:
        started = time.perf_counter()
        safe_limit = min(max(int(limit), 1), 20)
        try:
            with self.memory.connect() as db:
                table_name = next(
                    (
                        name
                        for name in TABLE_NAMES
                        if db.execute(
                            "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
                            ("table", name),
                        ).fetchone()
                    ),
                    None,
                )
                if table_name is None:
                    return ToolResult(
                        tool="lookup_table_rows",
                        success=False,
                        content="table rows store unavailable：当前SQLite没有表格行数据表。",
                        latency_ms=_elapsed_ms(started),
                        error="table_rows_store_unavailable",
                        metadata={"available": False, "rows": 0},
                    )

                # TABLE_NAMES is a fixed allowlist; no user input can become an identifier.
                schema = db.execute(f'PRAGMA table_info("{table_name}")').fetchall()
                existing = {str(row[1]) for row in schema}
                selected = [column for column in TABLE_COLUMNS if column in existing]
                searchable = [
                    column for column in SEARCHABLE_TABLE_COLUMNS if column in existing
                ]
                if not selected or not searchable:
                    return ToolResult(
                        tool="lookup_table_rows",
                        success=False,
                        content="table rows store unavailable：表格行数据表结构不受支持。",
                        latency_ms=_elapsed_ms(started),
                        error="table_rows_schema_unsupported",
                        metadata={"available": False, "rows": 0},
                    )

                terms = _search_terms(query or "") or [""]
                clauses: list[str] = []
                parameters: list[Any] = []
                for term in terms:
                    clauses.append(
                        "(" + " OR ".join(
                            f'LOWER(COALESCE("{column}", \'\')) LIKE ?'
                            for column in searchable
                        ) + ")"
                    )
                    parameters.extend([f"%{term}%"] * len(searchable))
                where = "(" + " OR ".join(clauses) + ")"
                if model and "model" in existing:
                    where += " AND (model = ? OR model = '' OR model IS NULL)"
                    parameters.append(model)
                version_match = VERSION_PATTERN.search(query or "")
                if version_match and "version" in existing:
                    where += " AND LOWER(COALESCE(version, '')) LIKE ?"
                    parameters.append(f"%{version_match.group(0).lower()}%")
                parameters.append(safe_limit)
                sql = (
                    "SELECT "
                    + ", ".join(f'"{column}"' for column in selected)
                    + f' FROM "{table_name}" WHERE {where} LIMIT ?'
                )
                rows = [dict(row) for row in db.execute(sql, parameters).fetchall()]
        except Exception as exc:
            return ToolResult(
                tool="lookup_table_rows",
                success=False,
                latency_ms=_elapsed_ms(started),
                error="sqlite_query_failed",
                metadata={"available": True, "rows": 0, "error_type": type(exc).__name__},
            )

        summaries: list[str] = []
        provenance: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            text = next(
                (
                    str(row[column])
                    for column in ("text", "content", "row_text")
                    if row.get(column) not in (None, "")
                ),
                "",
            )
            headers = row.get("headers") or row.get("header") or ""
            summaries.append(
                f"表格行{index}：{text or headers or '已匹配，但该行没有可展示文本。'}"
            )
            item = _provenance(row)
            if item:
                provenance.append(item)
        return ToolResult(
            tool="lookup_table_rows",
            success=True,
            content="\n".join(summaries) if summaries else "未找到匹配的表格行。",
            provenance=provenance,
            latency_ms=_elapsed_ms(started),
            metadata={
                "available": True,
                "table": table_name,
                "rows": len(rows),
                "limit": safe_limit,
                "citeable_evidence": False,
            },
        )
