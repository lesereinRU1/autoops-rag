from __future__ import annotations

from scripts import check_public_release


KNOWN_TEST_MARKER = b"sk-" + b"must-not-" + b"appear"


def test_known_runtime_metrics_marker_is_allowlisted() -> None:
    assert check_public_release.scan_content("fixture", KNOWN_TEST_MARKER) == []


def test_similar_marker_is_still_detected() -> None:
    similar_marker = KNOWN_TEST_MARKER + b"s"

    assert check_public_release.scan_content("fixture", similar_marker) == [
        "fixture: matched OpenAI-compatible API key"
    ]


def test_realistic_openai_compatible_key_shape_is_still_detected() -> None:
    realistic_key = b"sk-" + b"proj-A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"

    assert check_public_release.scan_content("fixture", realistic_key) == [
        "fixture: matched OpenAI-compatible API key"
    ]


def test_history_scan_uses_exact_allowlist_without_broadening(monkeypatch) -> None:
    unallowlisted_key = b"sk-" + b"history-A1b2C3d4E5f6"

    monkeypatch.setattr(
        check_public_release,
        "git",
        lambda *args: b"old patch " + KNOWN_TEST_MARKER,
    )
    assert check_public_release.scan_history() == []

    monkeypatch.setattr(
        check_public_release,
        "git",
        lambda *args: b"old patch " + KNOWN_TEST_MARKER + b"\nnew patch " + unallowlisted_key,
    )
    assert check_public_release.scan_history() == [
        "Git history: matched OpenAI-compatible API key"
    ]
