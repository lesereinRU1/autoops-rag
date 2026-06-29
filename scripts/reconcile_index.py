from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from qdrant_client import QdrantClient, models


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"autoops-rag:{chunk_id}"))


def main() -> None:
    settings = get_settings()
    expected = {
        point_id(json.loads(line)["chunk_id"])
        for line in settings.chunks_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    client = QdrantClient(path=str(settings.qdrant_path))
    before = int(client.count(settings.qdrant_collection, exact=True).count)
    existing: list[str] = []
    offset = None
    while True:
        records, offset = client.scroll(
            collection_name=settings.qdrant_collection,
            limit=512,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        existing.extend(str(record.id) for record in records)
        if offset is None:
            break
    stale = [identifier for identifier in existing if identifier not in expected]
    for start in range(0, len(stale), 512):
        client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=models.PointIdsList(points=stale[start : start + 512]),
            wait=True,
        )
    after = int(client.count(settings.qdrant_collection, exact=True).count)
    client.close()
    report = {
        "chunks_file": len(expected),
        "points_before": before,
        "stale_removed": len(stale),
        "points_after": after,
        "consistent": after == len(expected),
    }
    output = ROOT / "reports" / "index_reconciliation.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["consistent"]:
        raise SystemExit("Index reconciliation failed: point count does not match chunks file")


if __name__ == "__main__":
    main()
