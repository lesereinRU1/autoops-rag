from __future__ import annotations

import json
import os
import time
from pathlib import Path

from qdrant_client import QdrantClient

from app.config import get_settings
from app.ingestion.pipeline import ingest_corpus
from app.models import Chunk
from app.retrieval.vector_store import VectorStore, optimizer_config


SUPPORTED_RAW_SUFFIXES = {".pdf", ".txt", ".md", ".html", ".htm"}


def env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def load_chunks(path: Path) -> list[Chunk]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    chunks: list[Chunk] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                chunks.append(Chunk.model_validate(json.loads(line)))
            except Exception as exc:
                raise RuntimeError(
                    f"Invalid chunks file at line {line_number}: {path}"
                ) from exc
    return chunks


def raw_documents(raw_dir: Path) -> list[Path]:
    if not raw_dir.exists():
        return []
    return sorted(
        path
        for path in raw_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_RAW_SUFFIXES
    )


def wait_for_qdrant(url: str, api_key: str, timeout_seconds: float) -> QdrantClient:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        client = QdrantClient(
            url=url,
            api_key=api_key or None,
            timeout=min(10.0, timeout_seconds),
        )
        try:
            client.get_collections()
            return client
        except Exception as exc:
            last_error = exc
            client.close()
            time.sleep(2)
    raise RuntimeError(
        f"Qdrant did not become ready at {url} within {timeout_seconds:.0f} seconds"
    ) from last_error


def collection_count(client: QdrantClient, collection: str) -> int | None:
    if not client.collection_exists(collection):
        return None
    return int(client.count(collection, exact=True).count)


def index_existing_chunks(chunks: list[Chunk]) -> dict:
    store = VectorStore(get_settings())
    try:
        store.index(chunks, rebuild=True)
        return {
            "documents": len({chunk.doc_id for chunk in chunks}),
            "chunks": len(chunks),
            "mode": "existing_chunks",
            "embedding_backend": store.backend_name,
            "collection": store.settings.qdrant_collection,
        }
    finally:
        store.close()


def main() -> None:
    settings = get_settings()
    if not settings.qdrant_url:
        raise SystemExit(
            "Docker index initialization requires QDRANT_URL; embedded Qdrant is disabled."
        )

    wait_seconds = float(os.getenv("DOCKER_QDRANT_WAIT_SECONDS", "120"))
    client = wait_for_qdrant(
        settings.qdrant_url,
        settings.qdrant_api_key,
        wait_seconds,
    )
    try:
        existing = load_chunks(settings.chunks_file)
        points = collection_count(client, settings.qdrant_collection)
        if points is not None:
            client.update_collection(
                collection_name=settings.qdrant_collection,
                optimizers_config=optimizer_config(settings),
            )
    finally:
        client.close()

    force_reindex = env_flag("FORCE_REINDEX")
    if not force_reindex and existing and points == len(existing):
        print(
            json.dumps(
                {
                    "status": "ready",
                    "action": "skipped",
                    "collection": settings.qdrant_collection,
                    "chunks": len(existing),
                    "points": points,
                },
                ensure_ascii=False,
            )
        )
        return

    # A non-empty collection is treated as persistent user data.  A mismatch
    # can mean that chunks.jsonl and Qdrant came from different runs, so never
    # delete/rebuild it implicitly during `docker compose up`.
    if not force_reindex and points is not None and points > 0:
        raise SystemExit(
            "Existing Qdrant collection does not match data/processed/chunks.jsonl "
            f"(points={points}, chunks={len(existing)}). No data was changed. "
            "Inspect the mounted volumes, or explicitly run index-init with "
            "FORCE_REINDEX=true after confirming a rebuild is safe."
        )

    documents = raw_documents(settings.raw_dir)
    if force_reindex:
        if documents:
            result = ingest_corpus(
                mode=os.getenv("DOCKER_INGEST_MODE", "semantic"), rebuild=True
            )
            action = "rebuilt_from_raw"
        elif existing:
            result = index_existing_chunks(existing)
            action = "rebuilt_from_existing_chunks"
        else:
            raise SystemExit(
                "FORCE_REINDEX=true was requested, but neither data/raw documents "
                "nor data/processed/chunks.jsonl are available. No data was changed."
            )
    elif existing:
        result = index_existing_chunks(existing)
        action = "indexed_existing_chunks"
    elif documents:
        result = ingest_corpus(mode=os.getenv("DOCKER_INGEST_MODE", "semantic"), rebuild=True)
        action = "built_from_raw"
    else:
        raise SystemExit(
            "No index is available. Put legally obtained documents in data/raw, "
            "or restore data/processed/chunks.jsonl, then run docker compose up again."
        )

    client = wait_for_qdrant(
        settings.qdrant_url,
        settings.qdrant_api_key,
        wait_seconds,
    )
    try:
        final_points = collection_count(client, settings.qdrant_collection)
    finally:
        client.close()
    final_chunks = load_chunks(settings.chunks_file)
    if not final_chunks or final_points != len(final_chunks):
        raise SystemExit(
            "Index initialization finished with inconsistent chunk and Qdrant point counts."
        )

    print(
        json.dumps(
            {
                "status": "ready",
                "action": action,
                "collection": settings.qdrant_collection,
                "chunks": len(final_chunks),
                "points": final_points,
                "result": result,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
