from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PUBLIC_MANIFEST = ROOT / "data" / "sources.json"
LOCAL_MANIFEST = RAW / "sources.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(include_optional: bool = False) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    sources = json.loads(PUBLIC_MANIFEST.read_text(encoding="utf-8"))
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
        "Referer": "https://support.industry.siemens.com/",
    }
    with httpx.Client(follow_redirects=True, timeout=120, headers=headers) as client:
        for source in sources:
            if source.get("ingest") is False and not include_optional:
                continue
            target = RAW / source["filename"]
            if target.exists() and target.stat().st_size > 10_000:
                print(f"已有：{target.name} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
            else:
                print(f"下载：{source['title']}")
                with client.stream("GET", source["url"]) as response:
                    response.raise_for_status()
                    with target.open("wb") as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            output.write(chunk)
                print(f"完成：{target.name} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
            source["bytes"] = target.stat().st_size
            source["sha256"] = sha256(target)
    # Download sizes and hashes are machine-local run metadata. Keep them next
    # to the ignored raw files instead of dirtying the versioned source list.
    LOCAL_MANIFEST.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-optional", action="store_true", help="同时下载默认不入库的扩展资料")
    args = parser.parse_args()
    download(args.include_optional)
