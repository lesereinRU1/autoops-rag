from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.pipeline import ingest_corpus


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="解析原始资料、切块并写入本地 Qdrant")
    parser.add_argument("--mode", choices=["fixed", "semantic"], default="semantic")
    args = parser.parse_args()
    print(json.dumps(ingest_corpus(mode=args.mode, rebuild=True), ensure_ascii=False, indent=2))
