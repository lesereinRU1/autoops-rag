from __future__ import annotations

from app.models import SearchHit
from app.retrieval.bm25_retriever import tokenize_zh


class Reranker:
    def __init__(self, enabled: bool, model_name: str, cache_dir) -> None:
        self.model = None
        if enabled:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                self.model = TextCrossEncoder(model_name=model_name, cache_dir=str(cache_dir / "fastembed"))
            except Exception:
                self.model = None

    def rerank(self, query: str, hits: list[SearchHit], top_k: int = 5) -> list[SearchHit]:
        if not hits:
            return []
        if self.model is not None:
            scores = list(self.model.rerank(query, [hit.chunk.text for hit in hits]))
            for hit, score in zip(hits, scores, strict=True):
                hit.rerank_score = float(score)
            return sorted(hits, key=lambda item: item.rerank_score or 0.0, reverse=True)[:top_k]
        else:
            query_tokens = set(tokenize_zh(query))
            for hit in hits:
                doc_tokens = set(tokenize_zh(hit.chunk.text))
                overlap = len(query_tokens & doc_tokens) / max(1, len(query_tokens))
                hit.rerank_score = 0.7 * hit.score + 0.3 * overlap
            return sorted(hits, key=lambda item: item.rerank_score or 0.0, reverse=True)[:top_k]
