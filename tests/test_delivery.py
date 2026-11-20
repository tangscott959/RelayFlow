"""Unit tests for outbound delivery, Full Jitter backoff, and the DLQ threshold."""

from __future__ import annotations

import httpx
import pytest

from workers.delivery import (
    MAX_DELIVERY_ATTEMPTS,
    MAX_RESPONSE_BODY_CHARS,
    compute_full_jitter_delay,
    post_webhook,
    serialize_payload,
    should_move_to_dead_letter,
    _truncate_body,
)


def test_should_move_to_dead_letter_on_fifth_attempt() -> None:
    assert MAX_DELIVERY_ATTEMPTS == 5
    assert should_move_to_dead_letter(4) is False
    assert should_move_to_dead_letter(5) is True
    assert should_move_to_dead_letter(6) is True


def test_full_jitter_stays_within_exponential_cap() -> None:
    first = [compute_full_jitter_delay(1) for _ in range(40)]
    assert all(0.0 <= delay <= 1.0 for delay in first)

    second = [compute_full_jitter_delay(2) for _ in range(40)]
    assert all(0.0 <= delay <= 2.0 for delay in second)

    capped = [compute_full_jitter_delay(12) for _ in range(20)]
    assert all(0.0 <= delay <= 300.0 for delay in capped)


def test_serialize_payload_is_compact_utf8() -> None:
    body = serialize_payload({"ok": True, "nested": {"n": 1}})
    assert body == b'{"ok":true,"nested":{"n":1}}'


def test_truncate_body_caps_stored_response() -> None:
    oversized = "x" * (MAX_RESPONSE_BODY_CHARS + 10)
    truncated = _truncate_body(oversized)
    assert truncated is not None
    assert len(truncated) == MAX_RESPONSE_BODY_CHARS
    assert _truncate_body(None) is None


def test_post_webhook_success_signs_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 204
        headers = {"content-type": "application/json"}
        text = ""

    class Client:
        def __init__(self, timeout: float) -> None:
            assert timeout == 5.0

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def post(self, url: str, content: bytes, headers: dict[str, str]) -> Response:
            assert url == "https://example.com/hook"
            assert content == b"{}"
            assert headers["Content-Type"] == "application/json"
            assert headers["X-Agent-Timestamp"].isdigit()
            assert headers["X-Agent-Signature"].startswith("v1=")
            return Response()

    monkeypatch.setattr("workers.delivery.httpx.Client", Client)
    outcome = post_webhook("https://example.com/hook", "whsec_test", b"{}")

    assert outcome["succeeded"] is True
    assert outcome["http_status"] == 204
    assert outcome["duration_ms"] >= 0


def test_post_webhook_http_error_is_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class Client:
        def __init__(self, timeout: float) -> None:
            return None

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def post(self, url: str, content: bytes, headers: dict[str, str]) -> None:
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("workers.delivery.httpx.Client", Client)
    outcome = post_webhook("https://example.com/hook", "whsec_test", b"{}")

    assert outcome["succeeded"] is False
    assert outcome["http_status"] is None
    assert outcome["response_headers"] is None
    assert "connection refused" in (outcome["response_body"] or "")
