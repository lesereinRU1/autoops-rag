from __future__ import annotations

import uuid

from qdrant_client import QdrantClient, models

from app.config import Settings
from app.models import Chunk, SearchHit
from app.retrieval.embeddings import create_embedder


def optimizer_config(settings: Settings) -> models.OptimizersConfigDiff:
    """Keep small demo collections indexed instead of split into full-scan segments."""
    return models.OptimizersConfigDiff(
        indexing_threshold=max(0, settings.qdrant_indexing_threshold_kb),
        default_segment_number=max(1, settings.qdrant_default_segment_number),
    )


class VectorStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.embedder, self.dimension, self.backend_name = create_embedder(
            settings.embedding_backend,
            settings.embedding_model,
            settings.embedding_dim,
            settings.model_cache_dir,
        )
        if settings.qdrant_url:
            self.client = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key or None,
                timeout=settings.request_timeout_seconds,
            )
            self.storage_mode = "server"
        else:
            self.client = QdrantClient(path=str(settings.qdrant_path))
            self.storage_mode = "local"

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"autoops-rag:{chunk_id}"))

    def _collection_exists(self) -> bool:
        return self.client.collection_exists(self.settings.qdrant_collection)

    def index(self, chunks: list[Chunk], rebuild: bool = True, batch_size: int = 64) -> None:
        collection = self.settings.qdrant_collection
        if rebuild and self._collection_exists():
            self.client.delete_collection(collection)
        if not self._collection_exists():
            self.client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(size=self.dimension, distance=models.Distance.COSINE),
                optimizers_config=optimizer_config(self.settings),
            )

        for offset in range(0, len(chunks), batch_size):
            batch = chunks[offset : offset + batch_size]
            vectors = list(self.embedder.embed([chunk.text for chunk in batch]))
            points = [
                models.PointStruct(
                    id=self._point_id(chunk.chunk_id),
                    vector=np_vector.tolist() if hasattr(np_vector, "tolist") else np_vector,
                    payload=chunk.model_dump(),
                )
                for chunk, np_vector in zip(batch, vectors, strict=True)
            ]
            self.client.upsert(collection_name=collection, points=points, wait=True)
        if rebuild:
            self._prune_stale_points(collection, chunks)

    def _prune_stale_points(self, collection: str, chunks: list[Chunk]) -> int:
        """Remove points left by an interrupted rebuild and return the removed count."""
        expected = {self._point_id(chunk.chunk_id) for chunk in chunks}
        existing: list[str] = []
        offset = None
        while True:
            records, offset = self.client.scroll(
                collection_name=collection,
                limit=512,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            existing.extend(str(record.id) for record in records)
            if offset is None:
                break
        stale = [point_id for point_id in existing if point_id not in expected]
        for start in range(0, len(stale), 512):
            self.client.delete(
                collection_name=collection,
                points_selector=models.PointIdsList(points=stale[start : start + 512]),
                wait=True,
            )
        return len(stale)

    def search(self, query: str, top_k: int = 30, model: str = "", version: str = "") -> list[SearchHit]:
        if not self._collection_exists():
            return []
        query_vector = next(iter(self.embedder.embed([query])))
        conditions: list[models.FieldCondition] = []
        if model:
            conditions.append(models.FieldCondition(key="model", match=models.MatchValue(value=model)))
        if version:
            conditions.append(models.FieldCondition(key="version", match=models.MatchValue(value=version)))
        result = self.client.query_points(
            collection_name=self.settings.qdrant_collection,
            query=query_vector.tolist() if hasattr(query_vector, "tolist") else query_vector,
            query_filter=models.Filter(must=conditions) if conditions else None,
            limit=top_k,
            with_payload=True,
        )
        hits: list[SearchHit] = []
        for rank, point in enumerate(result.points, start=1):
            hits.append(
                SearchHit(
                    chunk=Chunk.model_validate(point.payload),
                    score=float(point.score),
                    dense_rank=rank,
                )
            )
        return hits

    def count(self) -> int:
        if not self._collection_exists():
            return 0
        return int(self.client.count(self.settings.qdrant_collection, exact=True).count)

    def close(self) -> None:
        self.client.close()
