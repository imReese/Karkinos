"""FastAPI 依赖注入。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from server.bridge import EventBusBridge
    from server.db import AppDatabase
    from server.scheduler import TradingScheduler
    from server.ws.hub import ConnectionHub


def get_scheduler(request: Request) -> TradingScheduler:
    return request.app.state.scheduler


def get_db(request: Request) -> AppDatabase:
    return request.app.state.db


def get_bridge(request: Request) -> EventBusBridge:
    return request.app.state.bridge


def get_hub(request: Request) -> ConnectionHub:
    return request.app.state.hub


def get_config(request: Request):
    return request.app.state.config
