"""HMAC-SHA256 signing and verification for webhook deliveries."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

WEBHOOK_SECRET_PREFIX = "whsec_"


def generate_endpoint_secret() -> str:
    """Return a cryptographically random endpoint signing secret.

    The value is prefixed with ``whsec_`` so operators can recognize webhook
    secrets at a glance (similar to Stripe / Svix conventions).
    """
    return f"{WEBHOOK_SECRET_PREFIX}{secrets.token_urlsafe(32)}"


def generate_signature(secret: str, payload_bytes: bytes, timestamp: int) -> str:
    """Return the hex HMAC-SHA256 digest for a webhook payload.

    The signed message is ``t={timestamp}.{payload}``, where ``payload`` is the
    raw request body bytes (not decoded as text).
    """
    signed_payload = f"t={timestamp}.".encode("utf-8") + payload_bytes
    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=signed_payload,
        digestmod=hashlib.sha256,
    )
    return digest.hexdigest()


def _parse_signature_header(signature_header: str) -> tuple[int | None, list[str]]:
    """Parse a header of the form ``t=<timestamp>,v1=<digest>[,v1=<digest>...]``."""
    timestamp: int | None = None
    signatures: list[str] = []

    for item in signature_header.split(","):
        part = item.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                return None, []
        elif key == "v1" and value:
            signatures.append(value)

    return timestamp, signatures


def verify_signature(
    payload_bytes: bytes,
    signature_header: str,
    secret: str,
    tolerance: int = 300,
) -> bool:
    """Validate an inbound signature header and reject replayed timestamps.

    Expected header format: ``t=<unix_ts>,v1=<hex_digest>``. Multiple ``v1``
    values are accepted (key rotation). The timestamp must fall within
    ``tolerance`` seconds of the current time (default 300s / 5 minutes).
    Signature comparison uses :func:`hmac.compare_digest`.
    """
    if not secret or not signature_header:
        return False

    timestamp, provided_signatures = _parse_signature_header(signature_header)
    if timestamp is None or not provided_signatures:
        return False

    now = int(time.time())
    if abs(now - timestamp) > tolerance:
        return False

    expected_signature = generate_signature(secret, payload_bytes, timestamp)
    matched = False
    for provided in provided_signatures:
        if hmac.compare_digest(expected_signature, provided):
            matched = True
    return matched
