from __future__ import annotations

import re


HEADING_PATTERNS = (
    re.compile(r"^#{1,6}\s+(.+)$"),
    re.compile(r"^(\d+(?:\.\d+){0,4})\s+(.{2,80})$"),
    re.compile(r"^([一二三四五六七八九十]+、.{2,80})$"),
)


def split_sections(text: str) -> list[tuple[list[str], str]]:
    """按 Markdown/数字标题拆章节；没有标题时返回整页。"""
    sections: list[tuple[list[str], str]] = []
    path: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        value = "\n".join(buffer).strip()
        if value:
            sections.append((path.copy(), value))
        buffer.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading: str | None = None
        level = 1
        markdown = HEADING_PATTERNS[0].match(line)
        numeric = HEADING_PATTERNS[1].match(line)
        chinese = HEADING_PATTERNS[2].match(line)
        if markdown:
            heading = markdown.group(1).strip()
            level = len(line) - len(line.lstrip("#"))
        elif numeric and not re.search(r"\.{3,}", line):
            heading = f"{numeric.group(1)} {numeric.group(2)}"
            level = min(4, numeric.group(1).count(".") + 1)
        elif chinese:
            heading = chinese.group(1).strip()
            level = 1

        if heading:
            flush()
            path[:] = path[: level - 1]
            path.append(heading[:100])
        else:
            buffer.append(raw_line)
    flush()
    return sections or [([], text.strip())]

