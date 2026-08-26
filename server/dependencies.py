"""Per-application state and FastAPI dependency adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

    from account_truth.broker_statement_collector import (
        LocalBrokerStatementCollector,
    )
    from notification.base import Notifier
    from server.bridge import EventBusBridge
    from server.config import ServerConfig
    from server.db import AppDatabase
    from server.scheduler import TradingScheduler
    from server.services.execution_gateway_verification import (
        ExecutionGatewayRuntimeProtocol,
    )
    from server.services.trading_controls import TradingControlState
    from server.ws.hub import ConnectionHub


class AppState:
    """Mutable runtime services owned by exactly one FastAPI application."""

    def __init__(self) -> None:
        self.config: ServerConfig | None = None
        self.db: AppDatabase | None = None
        self.hub: ConnectionHub | None = None
        self.bridge: EventBusBridge | None = None
        self.scheduler: TradingScheduler | None = None
        self.daily_decision_evidence_task: asyncio.Task[None] | None = None
        self.notifier: Notifier | None = None
        self.trading_controls: TradingControlState | None = None
        self.broker_statement_collector: LocalBrokerStatementCollector | None = None
        self.execution_gateways: list[ExecutionGatewayRuntimeProtocol] = []
        self.controlled_broker_release_evidence_provider: (
            Callable[[str], dict[str, Any]] | None
        ) = None

    def require_database(self) -> AppDatabase:
        """Return the initialized database or fail before composing a use case."""

        if self.db is None:
            raise RuntimeError("application database is not initialized")
        return self.db

    def require_config(self) -> ServerConfig:
        """Return the initialized runtime configuration or fail closed."""

        if self.config is None:
            raise RuntimeError("runtime configuration is not initialized")
        return self.config

    def application_container(self) -> ApplicationContainer:
        """Freeze the initialized application dependencies for use-case wiring."""

        return ApplicationContainer(
            config=self.require_config(),
            db=self.require_database(),
            trading_controls=self.trading_controls,
            execution_gateways=tuple(self.execution_gateways),
            controlled_broker_release_evidence_provider=(
                self.controlled_broker_release_evidence_provider
            ),
        )


@dataclass(frozen=True)
class ApplicationContainer:
    """Immutable, typed application dependencies consumed by composition roots."""

    config: ServerConfig
    db: AppDatabase
    trading_controls: TradingControlState | None
    execution_gateways: tuple[ExecutionGatewayRuntimeProtocol, ...]
    controlled_broker_release_evidence_provider: Callable[[str], dict[str, Any]] | None


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
    scheduler = _request_app_state(request).scheduler
    if scheduler is None:
        raise RuntimeError("trading scheduler is not initialized")
    return scheduler


def get_db(request: Request) -> AppDatabase:
    return _request_app_state(request).require_database()


def get_bridge(request: Request) -> EventBusBridge:
    bridge = _request_app_state(request).bridge
    if bridge is None:
        raise RuntimeError("event bridge is not initialized")
    return bridge


def get_hub(request: Request) -> ConnectionHub:
    hub = _request_app_state(request).hub
    if hub is None:
        raise RuntimeError("connection hub is not initialized")
    return hub


def get_config(request: Request) -> ServerConfig:
    return _request_app_state(request).require_config()


def _request_app_state(request: Request) -> AppState:
    state = getattr(request.app.state, "app_state", None)
    if not isinstance(state, AppState):
        raise RuntimeError("request is not bound to a Karkinos application state")
    return state
