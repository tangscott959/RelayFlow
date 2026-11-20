"""Test doubles that do not require PostgreSQL, Redis, or Celery."""

from __future__ import annotations


class DummyResult:
    def scalar_one_or_none(self) -> None:
        return None


class DummySession:
    """Async session stand-in that never talks to PostgreSQL."""

    async def scalar(self, *args: object, **kwargs: object) -> None:
        return None

    async def execute(self, *args: object, **kwargs: object) -> DummyResult:
        return DummyResult()

    def add(self, *args: object, **kwargs: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, *args: object, **kwargs: object) -> None:
        return None


class InMemoryRedis:
    """Minimal async Redis stand-in for idempotency GET/SET tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
