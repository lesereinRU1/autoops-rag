from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "raw" / "sources.json"
REPORT = ROOT / "reports" / "source_freshness.json"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def online_status(url: str) -> int | None:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true", help="also verify remote URLs")
    args = parser.parse_args()
    today = date.today()
    rows: list[dict] = []
    for source in json.loads(MANIFEST.read_text(encoding="utf-8")):
        path = MANIFEST.parent / source["filename"]
        checked = source.get("checked_at")
        age = (today - datetime.strptime(checked, "%Y-%m-%d").date()).days if checked else None
        row = {
            "filename": source["filename"],
            "title": source["title"],
            "version": source.get("version", ""),
            "ingest": bool(source.get("ingest")),
            "status": source.get("status", "unknown"),
            "checked_at": checked,
            "check_age_days": age,
            "local_exists": path.exists(),
            "local_bytes": path.stat().st_size if path.exists() else 0,
            "hash_matches": file_hash(path) == source.get("sha256") if path.exists() and source.get("sha256") else None,
        }
        if args.online:
            row["remote_http_status"] = online_status(source["url"])
        rows.append(row)
    active = [row for row in rows if row["ingest"]]
    report = {
        "checked_on": today.isoformat(),
        "sources_total": len(rows),
        "active_sources": len(active),
        "active_local_ready": sum(row["local_exists"] for row in active),
        "superseded_active": [row["filename"] for row in active if "superseded" in row["status"]],
        "sources": rows,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

