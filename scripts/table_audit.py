from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data" / "processed" / "chunks.jsonl"
REPORT = ROOT / "reports" / "table_extraction_audit.json"


def main() -> None:
    table_rows: list[dict] = []
    total = 0
    with CHUNKS.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            total += 1
            chunk = json.loads(line)
            if chunk.get("metadata", {}).get("representation") == "table_row":
                table_rows.append(chunk)
    url_markers = ("http://", "https://", "www.")
    suspicious_links = [
        row for row in table_rows
        if any(marker in (row["text"] + " " + " ".join(row["metadata"].get("headers", []))).lower()
               for marker in url_markers)
    ]
    samples: list[dict] = []
    sampled_per_document: Counter = Counter()
    for row in table_rows:
        if sampled_per_document[row["doc_name"]] >= 3:
            continue
        sampled_per_document[row["doc_name"]] += 1
        samples.append(
            {
                "chunk_id": row["chunk_id"],
                "document": row["doc_name"],
                "page": row["page"],
                "table_id": row["metadata"]["table_id"],
                "row_index": row["metadata"]["row_index"],
                "headers": row["metadata"]["headers"],
                "text": row["text"][:300],
            }
        )
    report = {
        "status": "passed" if not suspicious_links else "needs-review",
        "chunks_total": total,
        "table_row_chunks": len(table_rows),
        "table_row_ratio": round(len(table_rows) / total, 4) if total else 0.0,
        "tables": len({row["metadata"]["table_id"] for row in table_rows}),
        "table_pages": len({(row["doc_id"], row["page"]) for row in table_rows}),
        "documents": Counter(row["doc_name"] for row in table_rows),
        "quality_checks": {
            "link_layout_false_positives": len(suspicious_links),
            "rule": "strict ruled-line detection + at least two populated grid rows + occupancy >= 0.25 + URL layout rejection",
        },
        "samples": samples,
        "limitations": [
            "PyMuPDF table detection works best on text-based PDFs with visible row/column alignment.",
            "Scanned tables still require OCR and manual quality review.",
            "Merged cells and multi-page tables can require document-specific normalization.",
        ],
    }
    report["documents"] = dict(report["documents"])
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
