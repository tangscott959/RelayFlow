"""Unit tests for HMAC-SHA256 signing used on outbound deliveries."""

from __future__ import annotations

import time

from services.security import generate_endpoint_secret, generate_signature, verify_signature


def test_generate_and_verify_signature_round_trip() -> None:
    secret = "whsec_test_secret"
    payload = b'{"event":"order.created"}'
    timestamp = int(time.time())
    digest = generate_signature(secret, payload, timestamp)
    header = f"t={timestamp},v1={digest}"

    assert verify_signature(payload, header, secret) is True


def test_verify_signature_rejects_tampered_payload() -> None:
    secret = "whsec_test_secret"
    timestamp = int(time.time())
    digest = generate_signature(secret, b'{"event":"order.created"}', timestamp)
    header = f"t={timestamp},v1={digest}"

    assert verify_signature(b'{"event":"order.updated"}', header, secret) is False


def test_verify_signature_rejects_wrong_secret() -> None:
    payload = b'{"event":"order.created"}'
    timestamp = int(time.time())
    digest = generate_signature("whsec_correct", payload, timestamp)
    header = f"t={timestamp},v1={digest}"

    assert verify_signature(payload, header, "whsec_other") is False


def test_verify_signature_rejects_stale_timestamp() -> None:
    secret = "whsec_test_secret"
    payload = b'{"event":"order.created"}'
    timestamp = int(time.time()) - 400
    digest = generate_signature(secret, payload, timestamp)
    header = f"t={timestamp},v1={digest}"

    assert verify_signature(payload, header, secret) is False


def test_generate_endpoint_secret_uses_whsec_prefix() -> None:
    secret = generate_endpoint_secret()

    assert secret.startswith("whsec_")
    assert len(secret) > len("whsec_")
