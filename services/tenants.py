"""Tenant provisioning and API-key hashing."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Tenant

API_KEY_PREFIX = "rfk_"
API_KEY_PREFIX_DISPLAY_LENGTH = 12


def generate_api_key() -> str:
    """Return a high-entropy tenant API key prefixed with ``rfk_``."""

    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest used as the stored credential."""

    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def api_key_display_prefix(raw_key: str) -> str:
    """Return the public prefix shown after the secret is discarded."""

    return raw_key[:API_KEY_PREFIX_DISPLAY_LENGTH]


@dataclass(slots=True, frozen=True)
class CreatedTenant:
    tenant: Tenant
    api_key: str


async def create_tenant(*, session: AsyncSession, name: str) -> CreatedTenant:
    """Persist a tenant and return the plaintext API key once."""

    raw_key = generate_api_key()
    tenant = Tenant(
        name=name,
        api_key_hash=hash_api_key(raw_key),
        api_key_prefix=api_key_display_prefix(raw_key),
    )
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    return CreatedTenant(tenant=tenant, api_key=raw_key)


async def resolve_tenant_by_api_key(*, session: AsyncSession, raw_key: str) -> Tenant | None:
    """Look up a tenant by the SHA-256 of the presented API key."""

    digest = hash_api_key(raw_key)
    return await session.scalar(select(Tenant).where(Tenant.api_key_hash == digest))
