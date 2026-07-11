"""FastAPI app factory + lifespan。"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from server.bridge import EventBusBridge
from server.db import AppDatabase
from server.scheduler import TradingScheduler
from server.services.trading_controls import TradingControlState
from server.ws.hub import ConnectionHub

logger = logging.getLogger(__name__)
_SPA_RESERVED_PREFIXES = {"api", "ws"}
_DEFAULT_CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _env_flag(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_cors_allowed_origins(value: object) -> list[str]:
    if value is None:
        return list(_DEFAULT_CORS_ALLOWED_ORIGINS)
    if isinstance(value, str):
        origins = [origin.strip() for origin in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        origins = [str(origin).strip() for origin in value]
    else:
        origins = [str(value).strip()]
    origins = [origin for origin in origins if origin]
    return origins or list(_DEFAULT_CORS_ALLOWED_ORIGINS)


def _resolve_cors_allowed_origins(
    overrides: dict[str, Any],
    configured_default: object,
) -> list[str]:
    configured = (
        overrides["cors_allowed_origins"]
        if "cors_allowed_origins" in overrides
        else os.environ.get("KARKINOS_CORS_ALLOWED_ORIGINS")
    )
    if configured is None:
        configured = configured_default
    return _normalize_cors_allowed_origins(configured)


def _cors_allow_credentials(allowed_origins: list[str]) -> bool:
    # A wildcard origin is allowed only when explicitly configured. Disable
    # credentials in that mode so public examples do not ship a permissive
    # wildcard-plus-credentials CORS policy.
    return "*" not in allowed_origins


class AppState:
    """全局应用状态，供路由通过 get_app_state() 访问。"""

    def __init__(self) -> None:
        self.config: Any = None
        self.db: AppDatabase | None = None
        self.hub: ConnectionHub | None = None
        self.bridge: EventBusBridge | None = None
        self.scheduler: TradingScheduler | None = None
        self.notifier: Any = None
        self.trading_controls: TradingControlState | None = None


_app_state: AppState | None = None


def get_app_state() -> AppState:
    """获取全局应用状态。"""
    global _app_state
    if _app_state is None:
        _app_state = AppState()
    return _app_state


async def _forward_events(bridge: EventBusBridge, hub: ConnectionHub) -> None:
    """后台任务：从 bridge 队列消费事件，广播到所有 WebSocket 连接。"""
    while True:
        try:
            event_data = await bridge.get_event()
            await hub.broadcast(event_data)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error forwarding event")
            await asyncio.sleep(1)


def _confirm_pending_fund_orders_on_startup(state: AppState) -> None:
    """Confirm published fund subscriptions without blocking API startup."""
    try:
        from server.routes.portfolio import confirm_pending_fund_orders

        confirmed_count = confirm_pending_fund_orders(state)
        if confirmed_count:
            logger.info("Confirmed %d pending fund orders", confirmed_count)
    except Exception:
        logger.warning(
            "Failed to confirm pending fund orders during startup", exc_info=True
        )


def _is_spa_fallback_path(path: str) -> bool:
    requested = Path(path)
    if requested.suffix:
        return False
    first_part = requested.parts[0] if requested.parts else ""
    return first_part not in _SPA_RESERVED_PREFIXES


class SPAStaticFiles(StaticFiles):
    """StaticFiles with SPA index fallback for client-side routes."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not _is_spa_fallback_path(path):
                raise
            return await super().get_response("index.html", scope)

        if response.status_code != 404:
            return response

        if not _is_spa_fallback_path(path):
            return response

        return await super().get_response("index.html", scope)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    global _app_state

    state = get_app_state()

    # ---- Startup ----
    from core.event_bus import EventBus
    from notification.notifier import build_notifier
    from server.bootstrap import load_runtime_config
    from server.config import ServerConfig

    # create_app() loads the runtime config once and lifespan reuses the same
    # object so config.json remains a startup-only input.
    config_overrides = getattr(app.state, "config_overrides", {})
    config = getattr(app.state, "runtime_config", None)
    if config is None:
        config = load_runtime_config(ServerConfig, **config_overrides)
        app.state.runtime_config = config
    state.config = config

    # 初始化数据库
    db = AppDatabase()
    await db.init()
    migrated_marker = (
        db.get_runtime_control_sync("config_assets_migrated")
        if hasattr(db, "get_runtime_control_sync")
        else None
    )
    if getattr(config, "assets", None) and migrated_marker is None:
        migrated_count = db.seed_watchlist_assets_from_config_sync(config.assets)
        if hasattr(db, "set_runtime_control_sync"):
            db.set_runtime_control_sync(
                "config_assets_migrated",
                {"migrated_count": migrated_count},
            )
        if migrated_count:
            logger.info(
                "Migrated %d legacy config assets into watchlist_assets",
                migrated_count,
            )
    state.db = db

    # 初始化 WebSocket hub
    hub = ConnectionHub()
    state.hub = hub

    # 初始化 EventBusBridge
    loop = asyncio.get_event_loop()
    event_bus = EventBus()
    bridge = EventBusBridge(event_bus, loop)
    state.bridge = bridge

    # 初始化通知器
    notifier = build_notifier(config.notification)
    state.notifier = notifier

    # 初始化交易运行控制
    trading_controls = TradingControlState(db=db)
    state.trading_controls = trading_controls

    # 初始化调度器
    scheduler = TradingScheduler(
        config,
        bridge,
        notifier,
        db=db,
        trading_controls=trading_controls,
    )
    state.scheduler = scheduler

    # 存储到 app.state
    app.state.config = config
    app.state.db = db
    app.state.hub = hub
    app.state.bridge = bridge
    app.state.scheduler = scheduler
    app.state.notifier = notifier
    app.state.trading_controls = trading_controls

    # 启动事件转发任务
    forward_task = asyncio.create_task(_forward_events(bridge, hub))
    pending_confirm_thread = threading.Thread(
        target=_confirm_pending_fund_orders_on_startup,
        args=(state,),
        daemon=True,
        name="pending-fund-confirm",
    )
    pending_confirm_thread.start()

    # 自动启动实时监控
    if config.live_auto_start:
        scheduler.start()

    logger.info("Karkinos Server started")

    yield

    # ---- Shutdown ----
    forward_task.cancel()
    try:
        await forward_task
    except asyncio.CancelledError:
        pass

    scheduler.stop()
    bridge.stop()
    logger.info("Karkinos Server stopped")


def create_app(config_overrides: dict[str, Any] | None = None) -> FastAPI:
    """创建 FastAPI 应用实例。"""
    effective_overrides = dict(config_overrides or {})
    env_live_auto_start = _env_flag("KARKINOS_LIVE_AUTO_START")
    if env_live_auto_start is not None:
        effective_overrides.setdefault("live_auto_start", env_live_auto_start)
    from server.bootstrap import load_runtime_config
    from server.config import ServerConfig

    runtime_config = load_runtime_config(ServerConfig, **effective_overrides)

    app = FastAPI(
        title="Karkinos Server",
        description="面向中国市场的个人量化投研与交易平台",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.config_overrides = effective_overrides
    app.state.runtime_config = runtime_config
    cors_allowed_origins = _resolve_cors_allowed_origins(
        effective_overrides,
        getattr(runtime_config, "cors_allowed_origins", None),
    )
    cors_allow_credentials = _cors_allow_credentials(cors_allowed_origins)
    app.state.cors_allowed_origins = cors_allowed_origins
    app.state.cors_allow_credentials = cors_allow_credentials

    # CORS defaults are local-dev only. Use KARKINOS_CORS_ALLOWED_ORIGINS or
    # config_overrides["cors_allowed_origins"] for additional trusted origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_credentials=cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    from server.routes.acceptance_audit import create_router as acceptance_audit_router
    from server.routes.account_strategy import create_router as account_strategy_router
    from server.routes.account_truth import create_router as account_truth_router
    from server.routes.automation import create_router as automation_router
    from server.routes.backtest import create_router as backtest_router
    from server.routes.broker_connector_soak import (
        create_router as broker_connector_soak_router,
    )
    from server.routes.broker_gateway import create_router as broker_gateway_router
    from server.routes.capital_authorization import (
        create_router as capital_authorization_router,
    )
    from server.routes.capital_scaling_review import (
        create_router as capital_scaling_review_router,
    )
    from server.routes.controlled_session_budget_reservation import (
        create_router as controlled_session_budget_reservation_router,
    )
    from server.routes.controlled_session_envelope import (
        create_router as controlled_session_envelope_router,
    )
    from server.routes.decision import create_router as decision_router
    from server.routes.execution_gateway_verification import (
        create_router as execution_gateway_verification_router,
    )
    from server.routes.execution_reconciliation import (
        create_router as execution_reconciliation_router,
    )
    from server.routes.ledger import create_router as ledger_router
    from server.routes.market import create_router as market_router
    from server.routes.operations import create_router as operations_router
    from server.routes.per_order_confirmation import (
        create_router as per_order_confirmation_router,
    )
    from server.routes.portfolio import create_router as portfolio_router
    from server.routes.session_start_account_truth import (
        create_router as session_start_account_truth_router,
    )
    from server.routes.settings import create_router as settings_router
    from server.routes.signals import create_router as signals_router
    from server.routes.strategy_promotion import (
        create_router as strategy_promotion_router,
    )
    from server.routes.trading import create_router as trading_router
    from server.ws.handlers import router as ws_router

    app.include_router(market_router())
    app.include_router(acceptance_audit_router())
    app.include_router(account_strategy_router())
    app.include_router(account_truth_router())
    app.include_router(automation_router())
    app.include_router(broker_gateway_router())
    app.include_router(broker_connector_soak_router())
    app.include_router(capital_authorization_router())
    app.include_router(capital_scaling_review_router())
    app.include_router(controlled_session_envelope_router())
    app.include_router(controlled_session_budget_reservation_router())
    app.include_router(execution_reconciliation_router())
    app.include_router(execution_gateway_verification_router())
    app.include_router(ledger_router())
    app.include_router(operations_router())
    app.include_router(per_order_confirmation_router())
    app.include_router(session_start_account_truth_router())
    app.include_router(portfolio_router())
    app.include_router(signals_router())
    app.include_router(decision_router())
    app.include_router(strategy_promotion_router())
    app.include_router(backtest_router())
    app.include_router(settings_router())
    app.include_router(trading_router())
    app.include_router(ws_router)

    # 挂载前端静态文件（生产构建）
    dist_dir = Path("web/dist")
    if dist_dir.exists():
        app.mount(
            "/", SPAStaticFiles(directory=str(dist_dir), html=True), name="static"
        )

    return app
