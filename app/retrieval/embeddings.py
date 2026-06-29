from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path

import numpy as np


TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9_#.-]+")


class HashingEmbedder:
    """无需下载模型的确定性中文向量，保证项目离线也能工作。"""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _encode(self, text: str) -> list[float]:
        vector = np.zeros(self.dim, dtype=np.float32)
        tokens = TOKEN_PATTERN.findall(text.lower())
        chinese = [t for t in tokens if "\u4e00" <= t <= "\u9fff"]
        tokens.extend(a + b for a, b in zip(chinese, chinese[1:]))
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            index = value % self.dim
            sign = 1.0 if value & 1 else -1.0
            vector[index] += sign * (1.0 + math.log1p(len(token)))
        norm = float(np.linalg.norm(vector))
        if norm:
            vector /= norm
        return vector.tolist()

    def embed(self, texts: list[str]):
        for text in texts:
            yield self._encode(text)


def create_embedder(backend: str, model_name: str, dim: int, cache_dir: Path):
    if backend.lower() == "fastembed":
        os.environ.setdefault("HF_HOME", str(cache_dir / "huggingface"))
        os.environ.setdefault("FASTEMBED_CACHE_PATH", str(cache_dir / "fastembed"))
        from fastembed import TextEmbedding

        model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir / "fastembed"))
        sample = next(iter(model.embed(["维度检测"])))
        return model, int(len(sample)), "fastembed"
    return HashingEmbedder(dim), dim, "hash"

