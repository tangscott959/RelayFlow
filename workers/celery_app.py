"""Celery application bound to Redis as broker and result backend."""

from __future__ import annotations

from celery import Celery

from core.config import settings

celery_app = Celery("relayflow")

celery_app.conf.update(
    broker_url=settings.celery_broker_url or settings.redis_url,
    result_backend=settings.celery_result_backend or settings.redis_url,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    include=["workers.delivery"],
)
