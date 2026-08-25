from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import fitz

from app.models import Chunk, GetDocumentPageInput, SearchHit, ToolResult


class DocumentPageService:
    """Resolve one document page from indexed chunks, then an exact local PDF."""

    def __init__(self, chunks: dict[str, Chunk], raw_dir: Path) -> None:
        self.raw_dir = raw_dir
        self._pages: dict[tuple[str, int], list[Chunk]] = defaultdict(list)
        for chunk in chunks.values():
            references = {chunk.doc_id.casefold(), chunk.doc_name.casefold()}
            for reference in references:
                if reference:
                    self._pages[(reference, chunk.page)].append(chunk)

    @staticmethod
    def _references(arguments: GetDocumentPageInput) -> list[str]:
        return list(
            dict.fromkeys(
                value.casefold()
                for value in (arguments.document_id, arguments.document_name)
                if value
            )
        )

    def _from_chunks(self, arguments: GetDocumentPageInput) -> ToolResult | None:
        chunks: list[Chunk] = []
        seen: set[str] = set()
        for reference in self._references(arguments):
            for chunk in self._pages.get((reference, arguments.page), []):
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    chunks.append(chunk)
        if not chunks:
            return None
        chunks.sort(key=lambda item: item.chunk_id)
        evidence = [
            SearchHit(chunk=chunk, score=1.0, rerank_score=1.0) for chunk in chunks
        ]
        first = chunks[0]
        return ToolResult(
            tool_name="get_document_page",
            success=True,
            data={
                "document_id": first.doc_id,
                "document_name": first.doc_name,
                "page": arguments.page,
                "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            },
            result_count=len(chunks),
            evidence=evidence,
            provenance=[
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.doc_id,
                    "document_name": chunk.doc_name,
                    "page": chunk.page,
                    "source_url": chunk.source_url,
                }
                for chunk in chunks
            ],
            metadata={"source": "processed_chunks"},
        )

    def _matching_pdf(self, arguments: GetDocumentPageInput) -> Path | None:
        if not self.raw_dir.exists():
            return None
        references = set(self._references(arguments))
        references.update(Path(value).name.casefold() for value in list(references))
        for path in self.raw_dir.iterdir():
            if not path.is_file() or path.suffix.casefold() != ".pdf":
                continue
            if path.name.casefold() in references or path.stem.casefold() in references:
                return path
        return None

    def _from_pdf(self, arguments: GetDocumentPageInput) -> ToolResult | None:
        path = self._matching_pdf(arguments)
        if path is None:
            return None
        with fitz.open(path) as document:
            if arguments.page > document.page_count:
                return None
            page = document.load_page(arguments.page - 1)
            text = page.get_text("text").strip()
        return ToolResult(
            tool_name="get_document_page",
            success=True,
            data={
                "document_id": path.stem,
                "document_name": path.name,
                "page": arguments.page,
                "text": text,
            },
            result_count=1,
            provenance=[
                {
                    "document_id": path.stem,
                    "document_name": path.name,
                    "page": arguments.page,
                }
            ],
            metadata={"source": "raw_pdf"},
        )

    def get_page(self, arguments: GetDocumentPageInput) -> ToolResult:
        result = self._from_chunks(arguments) or self._from_pdf(arguments)
        if result is not None:
            return result
        return ToolResult(
            tool_name="get_document_page",
            success=False,
            data={},
            result_count=0,
            error="document_page_not_found",
            metadata={"found": False},
        )
