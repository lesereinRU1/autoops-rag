from __future__ import annotations

from fastapi.testclient import TestClient

import app.api as api


STATUS = {
    "embedding_backend": "hash",
    "embedding_model": "test-model",
    "collection": "test-collection",
    "qdrant_mode": "server",
    "query_expansion_enabled": False,
    "bm25_enabled": True,
    "max_concurrent_queries": 2,
    "request_timeout_seconds": 10.0,
    "rate_limit_per_minute": 30,
    "indexed_chunks": 3,
    "table_row_chunks": 0,
    "structured_tables": 0,
    "raw_files": 1,
    "active_sources": 1,
    "current_sources": 1,
    "latest_checked_at": "2026-07-02",
    "llm_enabled": False,
    "llm_model": "local",
    "llm_model_fallbacks": [],
}


class _Service:
    def status(self) -> dict:
        return dict(STATUS)

    def reindex(self, mode: str) -> dict:
        return {
            "documents": 1,
            "chunks": 3,
            "mode": mode,
            "embedding_backend": "hash",
            "collection": "test-collection",
        }

    def chat(self, *_args, **_kwargs):
        raise RuntimeError("D:/private/internal-secret-path")


def _client() -> TestClient:
    return TestClient(api.app, raise_server_exceptions=False)


def test_liveness_does_not_initialize_service(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_service",
        lambda: (_ for _ in ()).throw(RuntimeError("service must not load")),
    )

    response = _client().get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_is_full_but_redacts_dependency_errors(monkeypatch):
    monkeypatch.setattr(api, "get_service", lambda: _Service())
    ready = _client().get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["indexed_chunks"] == 3

    monkeypatch.setattr(
        api,
        "get_service",
        lambda: (_ for _ in ()).throw(RuntimeError("D:/private/qdrant-secret")),
    )
    failed = _client().get("/health/ready")
    assert failed.status_code == 503
    assert failed.json() == {"detail": "服务尚未就绪"}
    assert "private" not in failed.text


def test_index_ingest_is_disabled_without_admin_key(monkeypatch):
    monkeypatch.setattr(api.SETTINGS, "index_admin_api_key", "")

    response = _client().post("/api/index/ingest?mode=fixed")

    assert response.status_code == 503
    assert response.json() == {"detail": "索引维护接口未启用"}


def test_index_ingest_requires_and_accepts_admin_key(monkeypatch):
    monkeypatch.setattr(api.SETTINGS, "index_admin_api_key", "admin-test-key")
    monkeypatch.setattr(api, "get_service", lambda: _Service())
    client = _client()

    denied = client.post("/api/index/ingest?mode=fixed", headers={"X-Admin-Key": "wrong"})
    accepted = client.post(
        "/api/index/ingest?mode=fixed",
        headers={"X-Admin-Key": "admin-test-key"},
    )

    assert denied.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["mode"] == "fixed"


def test_chat_error_response_does_not_expose_internal_exception(monkeypatch):
    monkeypatch.setattr(api, "get_service", lambda: _Service())

    response = _client().post(
        "/api/chat",
        headers={"X-Request-ID": "safe-request-id"},
        json={"query": "测试问题"},
    )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "safe-request-id"
    assert response.json() == {"detail": "内部服务错误，请使用响应头 X-Request-ID 排查"}
    assert "private" not in response.text
