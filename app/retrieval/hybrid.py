from __future__ import annotations

from app.config import Settings
from app.models import SearchHit
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.reranker import Reranker
from app.retrieval.rrf import reciprocal_rank_fusion
from app.retrieval.query_expansion import expand_query
from app.retrieval.vector_store import VectorStore


class HybridRetriever:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.vector = VectorStore(settings)
        self.bm25 = BM25Retriever(settings.chunks_file)
        self.reranker = Reranker(settings.enable_reranker, settings.reranker_model, settings.model_cache_dir)

    @staticmethod
    def _trace_hits(hits: list[SearchHit]) -> list[dict]:
        return [
            {
                "rank": rank,
                "chunk_id": hit.chunk.chunk_id,
                "doc_name": hit.chunk.doc_name,
                "page": hit.chunk.page,
                "section_path": hit.chunk.section_path,
                "score": round(float(hit.score), 8),
                "dense_rank": hit.dense_rank,
                "bm25_rank": hit.bm25_rank,
                "rerank_score": (
                    round(float(hit.rerank_score), 8) if hit.rerank_score is not None else None
                ),
            }
            for rank, hit in enumerate(hits, start=1)
        ]

    def search_with_trace(
        self,
        query: str,
        top_k: int = 5,
        model: str = "S7-1200",
        version: str = "",
    ) -> tuple[list[SearchHit], dict]:
        prepared = expand_query(query)[0] if self.settings.enable_query_expansion else query
        # Candidate recall uses the original question. Expanded terms are applied only
        # during reranking so a dictionary addition cannot push an existing candidate
        # out of the Dense/BM25 Top30 pools.
        dense = self.vector.search(query, top_k=30, model=model, version=version)
        sparse = self.bm25.search(query, top_k=30, model=model, version=version)
        fused = reciprocal_rank_fusion([dense, sparse], k=60, limit=20)
        trace = {
            "dense_topk": self._trace_hits(dense),
            "bm25_topk": self._trace_hits(sparse),
            "rrf_topk": self._trace_hits(fused),
        }
        final = self.reranker.rerank(prepared, fused, top_k=top_k)
        trace["final_evidence"] = self._trace_hits(final)
        return final, trace

    def search(self, query: str, top_k: int = 5, model: str = "S7-1200", version: str = "") -> list[SearchHit]:
        hits, _ = self.search_with_trace(query, top_k=top_k, model=model, version=version)
        return hits

    def search_with_strategy(
        self,
        query: str,
        strategy: str = "hybrid",
        top_k: int = 5,
        model: str = "S7-1200",
        version: str = "",
    ) -> list[SearchHit]:
        prepared = expand_query(query)[0] if self.settings.enable_query_expansion else query
        if strategy == "dense":
            return self.vector.search(query, top_k=top_k, model=model, version=version)
        if strategy == "bm25":
            return self.bm25.search(query, top_k=top_k, model=model, version=version)
        return self.search(query, top_k=top_k, model=model, version=version)

    def close(self) -> None:
        self.vector.close()
