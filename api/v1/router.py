"""Aggregate v1 routes mounted under ``/api``."""

from __future__ import annotations

from fastapi import APIRouter

from api.v1 import deliveries, endpoints, events

api_router = APIRouter(prefix="/v1")
api_router.include_router(endpoints.router)
api_router.include_router(events.router)
api_router.include_router(deliveries.router)
