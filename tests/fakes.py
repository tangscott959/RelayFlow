"""Test doubles that do not require PostgreSQL, Redis, or Celery."""

from __future__ import annotations


class InMemoryRedis:
    """Minimal async Redis stand-in for idempotency GET/SET tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
