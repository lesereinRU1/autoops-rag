from __future__ import annotations

from collections import defaultdict

from app.models import SearchHit


def reciprocal_rank_fusion(rank_lists: list[list[SearchHit]], k: int = 60, limit: int = 20) -> list[SearchHit]:
    scores: dict[str, float] = defaultdict(float)
    hits: dict[str, SearchHit] = {}
    for rank_list in rank_lists:
        for rank, hit in enumerate(rank_list, start=1):
            cid = hit.chunk.chunk_id
            scores[cid] += 1.0 / (k + rank)
            if cid not in hits:
                hits[cid] = hit.model_copy(deep=True)
            else:
                if hit.dense_rank:
                    hits[cid].dense_rank = hit.dense_rank
                if hit.bm25_rank:
                    hits[cid].bm25_rank = hit.bm25_rank
    ordered = sorted(hits.values(), key=lambda item: scores[item.chunk.chunk_id], reverse=True)
    for hit in ordered:
        hit.score = scores[hit.chunk.chunk_id]
    return ordered[:limit]

