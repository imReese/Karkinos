"""Per-application state and FastAPI dependency adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

    from server.bridge import EventBusBridge
    from server.db import AppDatabase
    from server.scheduler import TradingScheduler
    from server.services.trading_controls import TradingControlState
    from server.ws.hub import ConnectionHub


class AppState:
    """Mutable runtime services owned by exactly one FastAPI application."""

    def __init__(self) -> None:
        self.config: Any = None
        self.db: AppDatabase | None = None
        self.hub: ConnectionHub | None = None
        self.bridge: EventBusBridge | None = None
        self.scheduler: TradingScheduler | None = None
        self.daily_decision_evidence_task: asyncio.Task[None] | None = None
        self.notifier: Any = None
        self.trading_controls: TradingControlState | None = None
        self.broker_statement_collector: Any = None


_current_app_state: ContextVar[AppState | None] = ContextVar(
    "karkinos_current_app_state",
    default=None,
)


def get_app_state() -> AppState:
    """Return state for the current request or explicitly bound app context."""
    state = _current_app_state.get()
    if state is None:
        raise RuntimeError(
            "Karkinos application state is unavailable outside a bound request "
            "or application context"
        )
    return state


@contextmanager
def bind_app_state(state: AppState) -> Iterator[AppState]:
    """Temporarily bind one application's state to the current context."""
    token = _current_app_state.set(state)
    try:
        yield state
    finally:
        _current_app_state.reset(token)


class AppStateContextMiddleware:
    """Bind the owning application's state for each ASGI request scope."""

    def __init__(self, app: ASGIApp, *, app_state: AppState) -> None:
        self.app = app
        self.app_state = app_state

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        with bind_app_state(self.app_state):
            await self.app(scope, receive, send)


def get_scheduler(request: Request) -> TradingScheduler:
    return request.app.state.app_state.scheduler


def get_db(request: Request) -> AppDatabase:
    return request.app.state.app_state.db


def get_bridge(request: Request) -> EventBusBridge:
    return request.app.state.app_state.bridge


def get_hub(request: Request) -> ConnectionHub:
    return request.app.state.app_state.hub


def get_config(request: Request):
    return request.app.state.app_state.config
