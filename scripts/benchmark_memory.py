from __future__ import annotations

import json
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVAL_FILE = ROOT / "data" / "eval" / "memory_questions.jsonl"
REPORT_FILE = ROOT / "reports" / "memory_evaluation.json"
API_URL = "http://127.0.0.1:8000"


def chat(question: str, session_id: str) -> dict:
    payload = {
        "query": question,
        "model": "S7-1200",
        "version": "",
        "top_k": 5,
        "strategy": "hybrid",
        "session_id": session_id,
    }
    request = urllib.request.Request(
        f"{API_URL}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def clear(session_id: str) -> int:
    request = urllib.request.Request(
        f"{API_URL}/api/sessions/{urllib.parse.quote(session_id)}", method="DELETE"
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return int(json.loads(response.read().decode("utf-8"))["removed_turns"])


def main() -> None:
    rows = [
        json.loads(line)
        for line in EVAL_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cases: list[dict] = []
    for row in rows:
        session_id = f"memory-eval-{uuid.uuid4().hex}"
        first = chat(row["first"], session_id)
        followup = chat(row["followup"], session_id)
        answer = followup["answer"]
        context_ok = followup["runtime"]["context_turns_used"] >= 1
        tool_ok = followup["selected_tool"] == row["expected_tool"]
        answer_ok = all(value in answer for value in row["expected_contains"])
        removed = clear(session_id)
        cases.append(
            {
                "id": row["id"],
                "context_turns_used": followup["runtime"]["context_turns_used"],
                "context_ok": context_ok,
                "tool_ok": tool_ok,
                "answer_ok": answer_ok,
                "clear_ok": removed == 2,
                "first_tool": first["selected_tool"],
                "followup_tool": followup["selected_tool"],
            }
        )
    total = len(cases)
    report = {
        "evaluation_type": "deterministic-two-turn-followup-pilot",
        "cases": total,
        "context_use_rate": round(sum(case["context_ok"] for case in cases) / total, 4),
        "tool_accuracy": round(sum(case["tool_ok"] for case in cases) / total, 4),
        "answer_check_rate": round(sum(case["answer_ok"] for case in cases) / total, 4),
        "session_clear_rate": round(sum(case["clear_ok"] for case in cases) / total, 4),
        "details": cases,
        "limitations": [
            "Only three deterministic two-turn cases are included.",
            "The current resolver handles bounded technical follow-ups, not unrestricted conversation.",
            "Expand with independently reviewed field questions before production use.",
        ],
    }
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if any(not (case["context_ok"] and case["tool_ok"] and case["answer_ok"] and case["clear_ok"]) for case in cases):
        raise SystemExit("Multi-turn evaluation has failed cases")


if __name__ == "__main__":
    main()
