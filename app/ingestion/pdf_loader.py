from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import fitz


TABLE_CACHE_VERSION = "v2-lines-strict"


@dataclass
class DocumentPage:
    doc_id: str
    doc_name: str
    page: int
    text: str
    metadata: dict = field(default_factory=dict)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)


def _clean_text(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\x00", " ")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_cell(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _looks_like_link_layout(values: list[str]) -> bool:
    """Reject hyperlink wrapping that PDF table detection mistakes for columns."""
    joined = " ".join(values).lower()
    return any(marker in joined for marker in ("http://", "https://", "www."))


def _table_title(page, bbox) -> str:
    """Pick the closest short text block above a detected table as its title."""
    candidates: list[tuple[float, str]] = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, *_ = block
        if y1 <= bbox[1] and 0 <= bbox[1] - y1 <= 90:
            cleaned = _clean_text(text).replace("\n", " ")
            if cleaned and len(cleaned) <= 160:
                candidates.append((y1, cleaned))
    return max(candidates, default=(0.0, ""), key=lambda item: item[0])[1]


def _unique_headers(first_row: list[str], width: int) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}
    for index in range(width):
        base = _clean_cell(first_row[index] if index < len(first_row) else "") or f"column_{index + 1}"
        seen[base] = seen.get(base, 0) + 1
        headers.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return headers


def _table_row_pages(page, did: str, doc_name: str, page_number: int, meta: dict) -> list[DocumentPage]:
    result: list[DocumentPage] = []
    try:
        detected = page.find_tables(strategy="lines_strict").tables
    except Exception:
        return result
    for table_index, table in enumerate(detected, start=1):
        raw_rows = table.extract() or []
        rows = [[_clean_cell(cell) for cell in row] for row in raw_rows if row]
        if not rows:
            continue
        width = max(len(row) for row in rows)
        if width < 2:
            continue
        nonempty_per_row = [sum(bool(cell) for cell in row) for row in rows]
        grid_rows = sum(count >= 2 for count in nonempty_per_row)
        occupancy = sum(nonempty_per_row) / max(1, len(rows) * width)
        if grid_rows < 2 or occupancy < 0.25:
            continue
        if _looks_like_link_layout([cell for row in rows for cell in row]):
            continue
        headers = _unique_headers(rows[0], width)
        data_rows = rows[1:] if len(rows) > 1 else rows
        title = _table_title(page, table.bbox) or f"表格 {page_number}-{table_index}"
        table_id = f"{did}_p{page_number:04d}_t{table_index:02d}"
        for row_index, row in enumerate(data_rows, start=1):
            padded = row + [""] * (width - len(row))
            pairs = [f"{header}={value}" for header, value in zip(headers, padded) if value]
            if not pairs:
                continue
            row_text = f"{title}\n表格行：" + "；".join(pairs)
            row_meta = dict(meta)
            row_meta.update(
                {
                    "representation": "table_row",
                    "table_id": table_id,
                    "table_index": table_index,
                    "row_index": row_index,
                    "headers": headers,
                    "table_title": title,
                    "bbox": [round(float(value), 2) for value in table.bbox],
                }
            )
            result.append(DocumentPage(did, doc_name, page_number, row_text, row_meta))
    return result


def _table_cache_path(raw_dir: Path, did: str) -> Path:
    cache_dir = raw_dir.parent / "processed" / "table_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{did}_{TABLE_CACHE_VERSION}.jsonl"


def _load_table_cache(path: Path) -> list[DocumentPage] | None:
    if not path.exists():
        return None
    pages: list[DocumentPage] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                page = DocumentPage(**json.loads(line))
                headers = [str(value) for value in page.metadata.get("headers", [])]
                if not _looks_like_link_layout(headers + [page.text]):
                    pages.append(page)
    return pages


def _write_table_cache(path: Path, pages: list[DocumentPage]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for page in pages:
            handle.write(
                json.dumps(
                    {
                        "doc_id": page.doc_id,
                        "doc_name": page.doc_name,
                        "page": page.page,
                        "text": page.text,
                        "metadata": page.metadata,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _load_manifest(raw_dir: Path) -> dict[str, dict]:
    manifest_path = raw_dir / "sources.json"
    if not manifest_path.exists():
        return {}
    rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {row["filename"]: row for row in rows}


def _doc_id(path: Path) -> str:
    digest = hashlib.sha1(path.read_bytes()).hexdigest()[:10]
    return f"{path.stem.lower().replace(' ', '_')}_{digest}"


def load_documents(raw_dir: Path, extract_tables: bool = True) -> list[DocumentPage]:
    manifest = _load_manifest(raw_dir)
    pages: list[DocumentPage] = []
    supported = {".pdf", ".txt", ".md", ".html", ".htm"}
    for path in sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in supported):
        meta = dict(manifest.get(path.name, {}))
        if meta.get("ingest") is False:
            continue
        did = _doc_id(path)
        if path.suffix.lower() == ".pdf":
            document_pages: list[DocumentPage] = []
            cache_path = _table_cache_path(raw_dir, did)
            cached_tables = _load_table_cache(cache_path) if extract_tables else []
            table_pages: list[DocumentPage] = cached_tables or []
            with fitz.open(path) as pdf:
                for index, page in enumerate(pdf):
                    text = _clean_text(page.get_text("text"))
                    if len(text) >= 30:
                        page_meta = dict(meta)
                        page_meta["representation"] = "page_text"
                        document_pages.append(DocumentPage(did, path.name, index + 1, text, page_meta))
                    if extract_tables and cached_tables is None:
                        table_pages.extend(_table_row_pages(page, did, path.name, index + 1, meta))
            if extract_tables and cached_tables is None:
                _write_table_cache(cache_path, table_pages)
            # Keep full-page text for narrative context and append structured table rows
            # afterwards. This dual representation preserves existing chunk ids while
            # making row/column semantics independently retrievable.
            pages.extend(document_pages)
            pages.extend(table_pages)
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if path.suffix.lower() in {".html", ".htm"}:
                parser = _HTMLTextExtractor()
                parser.feed(text)
                text = "\n".join(parser.parts)
            text = _clean_text(text)
            text_meta = dict(meta)
            text_meta["representation"] = "page_text"
            pages.append(DocumentPage(did, path.name, 1, text, text_meta))
    return pages
