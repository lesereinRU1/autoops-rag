from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_PATHS = (
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)\.env\.(?!example$)"),
    re.compile(r"(^|/)data/raw/"),
    re.compile(r"(^|/)models/"),
    re.compile(r"(^|/)storage/"),
    re.compile(r"\.(?:pdf|docx|xlsx|pptx|p12|pfx|pem|key)$", re.IGNORECASE),
)
SECRET_PATTERNS = {
    "OpenAI-compatible API key": re.compile(rb"\bsk-[A-Za-z0-9][A-Za-z0-9._-]{11,}\b"),
    "Bearer token": re.compile(rb"(?i)\bBearer\s+[A-Za-z0-9][A-Za-z0-9._-]{19,}\b"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential in URL": re.compile(rb"https?://[^\s/:]+:[^\s/@]+@"),
}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def candidate_files() -> list[str]:
    raw = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted(path.decode("utf-8") for path in raw.split(b"\0") if path)


def scan_content(label: str, content: bytes) -> list[str]:
    findings: list[str] = []
    if b"\0" in content:
        return findings
    for name, pattern in SECRET_PATTERNS.items():
        if pattern.search(content):
            findings.append(f"{label}: matched {name}")
    return findings


def scan_files() -> list[str]:
    findings: list[str] = []
    for relative in candidate_files():
        normalized = relative.replace("\\", "/")
        if Path(normalized).name != ".gitkeep" and any(
            pattern.search(normalized) for pattern in SENSITIVE_PATHS
        ):
            findings.append(f"{relative}: sensitive path must not be published")
            continue
        path = ROOT / relative
        if path.is_file():
            findings.extend(scan_content(relative, path.read_bytes()))
    return findings


def scan_history() -> list[str]:
    try:
        patch = git("log", "--all", "-p", "--no-ext-diff", "--binary")
    except subprocess.CalledProcessError:
        return ["unable to scan Git history"]
    return [
        f"Git history: matched {name}"
        for name, pattern in SECRET_PATTERNS.items()
        if pattern.search(patch)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether the repository is safe to publish.")
    parser.add_argument("--history", action="store_true", help="also scan every Git commit")
    args = parser.parse_args()

    findings = scan_files()
    if args.history:
        findings.extend(scan_history())
    if findings:
        print("Public-release check failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Public-release check passed: no tracked/visible credentials or private data paths found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
