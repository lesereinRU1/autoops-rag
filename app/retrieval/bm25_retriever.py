from __future__ import annotations

import json
import re

import jieba
from rank_bm25 import BM25Okapi

from app.config import PROJECT_ROOT
from app.models import Chunk, SearchHit


TECH_PATTERN = re.compile(r"16#[0-9a-f]+|[a-z][a-z0-9_]+|\d+(?:\.\d+)?", re.I)
JIEBA_CACHE_DIR = PROJECT_ROOT / ".cache" / "jieba"
JIEBA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
jieba.dt.tmp_dir = str(JIEBA_CACHE_DIR)
jieba.dt.cache_file = "jieba.cache"


def tokenize_zh(text: str) -> list[str]:
    normalized = text.lower().replace("s7 1200", "s7-1200")
    words = [word.strip() for word in jieba.lcut(normalized) if word.strip()]
    words.extend(TECH_PATTERN.findall(normalized))
    return words


class BM25Retriever:
    def __init__(self, chunks_file) -> None:
        self.chunks: list[Chunk] = []
        if chunks_file.exists():
            with chunks_file.open("r", encoding="utf-8") as handle:
                self.chunks = [Chunk.model_validate(json.loads(line)) for line in handle if line.strip()]
        self.corpus = [tokenize_zh(chunk.text) for chunk in self.chunks]
        self.index = BM25Okapi(self.corpus) if self.corpus else None

    def search(self, query: str, top_k: int = 30, model: str = "", version: str = "") -> list[SearchHit]:
        if self.index is None:
            return []
        scores = self.index.get_scores(tokenize_zh(query))
        candidates = sorted(range(len(scores)), key=lambda i: float(scores[i]), reverse=True)
        hits: list[SearchHit] = []
        for index in candidates:
            chunk = self.chunks[index]
            if model and chunk.model and chunk.model.lower() != model.lower():
                continue
            if version and chunk.version and chunk.version.lower() != version.lower():
                continue
            if scores[index] <= 0 and hits:
                break
            hits.append(SearchHit(chunk=chunk, score=float(scores[index]), bm25_rank=len(hits) + 1))
            if len(hits) >= top_k:
                break
        return hits
