from app.models import Chunk, SearchHit
from app.retrieval.rrf import reciprocal_rank_fusion


def hit(cid: str) -> SearchHit:
    return SearchHit(chunk=Chunk(chunk_id=cid, doc_id="d", doc_name="x", text="正文"), score=1.0)


def test_rrf_rewards_documents_present_in_both_lists():
    fused = reciprocal_rank_fusion([[hit("a"), hit("b")], [hit("b"), hit("c")]])
    assert fused[0].chunk.chunk_id == "b"

