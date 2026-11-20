"""Unit tests for tenant API-key generation and hashing."""

from __future__ import annotations

from services.tenants import API_KEY_PREFIX, api_key_display_prefix, generate_api_key, hash_api_key


def test_generate_api_key_uses_rfk_prefix() -> None:
    key = generate_api_key()
    assert key.startswith(API_KEY_PREFIX)
    assert len(key) > len(API_KEY_PREFIX)


def test_hash_api_key_is_stable_sha256_hex() -> None:
    key = "rfk_test_secret"
    digest = hash_api_key(key)
    assert digest == hash_api_key(key)
    assert digest != hash_api_key("rfk_other")
    assert len(digest) == 64
    assert digest.isalnum()


def test_api_key_display_prefix_is_truncated() -> None:
    key = generate_api_key()
    prefix = api_key_display_prefix(key)
    assert prefix == key[:12]
    assert prefix.startswith(API_KEY_PREFIX)
