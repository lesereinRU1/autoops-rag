from __future__ import annotations

import threading
import time

from app.concurrency import ReadWriteLock
from app.config import Settings
from app.http_guard import SlidingWindowRateLimiter
from app.models import Chunk, SearchHit
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.query_expansion import expand_query
from app.retrieval.query_expansion import technical_terms
from app.service import AutoOpsService


def make_hit(cid: str, text: str, doc_name: str, score: float) -> SearchHit:
    return SearchHit(
        chunk=Chunk(chunk_id=cid, doc_id="d", doc_name=doc_name, text=text),
        score=score,
    )


def test_query_expansion_adds_audited_english_terms():
    expanded, additions = expand_query("RD_MB_DATA_LEN允许读取多少个寄存器？")
    assert "permitted values" in expanded
    assert "number of registers" in additions
    assert "read" in additions


def test_technical_terms_do_not_match_zero_inside_another_number():
    query_terms = technical_terms("MB_MODE=0 MB_DATA_ADDR=40,001")
    wrong_terms = technical_terms("MB_MODE=1 MB_DATA_ADDR=40,001")
    right_terms = technical_terms("MB_MODE=0 MB_DATA_ADDR=40,001 Modbus function=03")
    assert "0" in query_terms
    assert "0" not in wrong_terms
    assert "0" in right_terms


def test_identifier_evidence_gate_rejects_unmatched_code():
    evidence = [make_hit("c1", "STATUS 16#80C8 no response", "manual.pdf", 1.0)]
    assert AutoOpsService.evidence_supports_query("16#80C8是什么意思", evidence)
    assert not AutoOpsService.evidence_supports_query("16#DEAD是什么意思", evidence)


def test_rate_limiter_and_read_write_lock_allow_concurrent_readers():
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)
    assert limiter.check("client", now=1.0)[0]
    assert limiter.check("client", now=2.0)[0]
    assert not limiter.check("client", now=3.0)[0]

    lock = ReadWriteLock()
    active = 0
    maximum = 0
    guard = threading.Lock()

    def reader():
        nonlocal active, maximum
        with lock.read():
            with guard:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.03)
            with guard:
                active -= 1

    threads = [threading.Thread(target=reader) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert maximum >= 2


def test_rate_limiter_bounds_tracked_clients():
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60, max_clients=3)

    for index in range(10):
        assert limiter.check(f"client-{index}", now=float(index))[0]

    assert limiter.tracked_clients == 3


def test_disabled_bm25_uses_dense_without_building_sparse_index(monkeypatch):
    dense_hit = make_hit("dense", "dense evidence", "demo.md", 0.9)

    class FakeVectorStore:
        backend_name = "hash"

        def __init__(self, _settings):
            pass

        def search(self, *_args, **_kwargs):
            return [dense_hit]

        def close(self):
            pass

    class FakeReranker:
        def __init__(self, *_args, **_kwargs):
            pass

        def rerank(self, _query, hits, top_k):
            return hits[:top_k]

    monkeypatch.setattr("app.retrieval.hybrid.VectorStore", FakeVectorStore)
    monkeypatch.setattr("app.retrieval.hybrid.Reranker", FakeReranker)
    monkeypatch.setattr(
        "app.retrieval.hybrid.BM25Retriever",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("BM25 must stay disabled")),
    )

    retriever = HybridRetriever(Settings(_env_file=None, enable_bm25=False))

    assert retriever.bm25 is None
    assert retriever.search_with_strategy("query", strategy="bm25") == [dense_hit]
