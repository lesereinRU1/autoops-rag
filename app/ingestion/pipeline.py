from __future__ import annotations

import json
from collections.abc import Callable

from app.config import Settings, get_settings
from app.ingestion.pdf_loader import load_documents
from app.ingestion.semantic_chunker import fixed_chunks, semantic_chunks
from app.ingestion.structure_parser import split_sections
from app.models import Chunk


def build_chunks(settings: Settings, mode: str = "semantic") -> list[Chunk]:
    pages = load_documents(settings.raw_dir, extract_tables=settings.enable_table_extraction)
    chunks: list[Chunk] = []
    chunker: Callable[[str], list[str]]
    if mode == "fixed":
        chunker = lambda text: fixed_chunks(text, settings.chunk_size, settings.chunk_overlap)
    else:
        chunker = semantic_chunks

    counters: dict[str, int] = {}
    for page in pages:
        meta = page.metadata
        for section_path, section_text in split_sections(page.text):
            for text in chunker(section_text):
                indexed_text = (
                    f"{' > '.join(section_path)}\n{text}" if section_path else text
                )
                counters[page.doc_id] = counters.get(page.doc_id, 0) + 1
                number = counters[page.doc_id]
                chunk_id = f"{page.doc_id}_{page.page:04d}_{number:04d}"
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        doc_id=page.doc_id,
                        doc_name=meta.get("title", page.doc_name),
                        text=indexed_text,
                        page=page.page,
                        section_path=section_path,
                        manufacturer=meta.get("manufacturer", "Siemens"),
                        model=meta.get("model", "S7-1200"),
                        version=meta.get("version", ""),
                        source_url=meta.get("url", ""),
                        metadata={
                            "filename": page.doc_name,
                            "license_note": meta.get("license_note", ""),
                            **{
                                key: meta[key]
                                for key in (
                                    "representation", "table_id", "table_index", "row_index",
                                    "headers", "table_title", "bbox", "released_at", "checked_at", "status",
                                )
                                if key in meta
                            },
                        },
                    )
                )
    return chunks


def ingest_corpus(mode: str = "semantic", rebuild: bool = True) -> dict:
    from app.retrieval.vector_store import VectorStore

    settings = get_settings()
    chunks = build_chunks(settings, mode=mode)
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    with settings.chunks_file.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.model_dump(), ensure_ascii=False) + "\n")
    store = VectorStore(settings)
    store.index(chunks, rebuild=rebuild)
    return {
        "documents": len({chunk.doc_id for chunk in chunks}),
        "chunks": len(chunks),
        "mode": mode,
        "embedding_backend": store.backend_name,
        "collection": settings.qdrant_collection,
    }
