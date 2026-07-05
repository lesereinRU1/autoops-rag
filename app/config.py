from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8000
    embedding_backend: str = "hash"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dim: int = 512
    enable_reranker: bool = False
    enable_bm25: bool = True
    enable_table_extraction: bool = True
    reranker_model: str = "BAAI/bge-reranker-base"
    qdrant_collection: str = "autoops_manuals"
    qdrant_indexing_threshold_kb: int = 5000
    qdrant_default_segment_number: int = 2
    chunk_size: int = 450
    chunk_overlap: int = 60
    enable_query_expansion: bool = False
    max_concurrent_queries: int = 8
    request_timeout_seconds: float = 90.0
    rate_limit_per_minute: int = 300
    rate_limit_max_clients: int = 10000
    index_admin_api_key: str = ""
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    llm_enabled: bool = False
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "qwen-plus"
    model_name: str = ""
    model_fallbacks: str = ""
    llm_timeout_seconds: float = 40.0
    llm_transport_retries: int = 1
    enable_agentic_rag: bool = False
    enable_agentic_routing: bool = False
    enable_agentic_planner: bool = False
    enable_sqlite_table_tool: bool = False
    enable_iterative_retrieval: bool = False
    max_agent_rounds: int = 2
    max_tool_calls: int = 4
    max_llm_calls: int = 2
    agent_timeout_seconds: float = 60.0
    max_rewrites: int = 1

    @property
    def llm_primary_model(self) -> str:
        """MODEL_NAME takes precedence while LLM_MODEL remains backward compatible."""
        return self.model_name.strip() or self.llm_model.strip() or "qwen-plus"

    @property
    def llm_model_candidates(self) -> list[str]:
        candidates = [self.llm_primary_model]
        candidates.extend(
            value.strip() for value in self.model_fallbacks.split(",") if value.strip()
        )
        return list(dict.fromkeys(candidates))

    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / "data"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def chunks_file(self) -> Path:
        return self.processed_dir / "chunks.jsonl"

    @property
    def qdrant_path(self) -> Path:
        return PROJECT_ROOT / "storage" / "qdrant"

    @property
    def sqlite_path(self) -> Path:
        return PROJECT_ROOT / "storage" / "autoops.db"

    @property
    def model_cache_dir(self) -> Path:
        return PROJECT_ROOT / "models"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    for path in (
        settings.raw_dir,
        settings.processed_dir,
        settings.qdrant_path.parent,
        settings.model_cache_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return settings
