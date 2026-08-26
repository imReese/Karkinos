"""FastAPI app factory + lifespan。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from server import __version__
from server.bridge import EventBusBridge
from server.db import AppDatabase
from server.dependencies import (
    AppState,
    AppStateContextMiddleware,
    bind_app_state,
)
from server.scheduler import TradingScheduler
from server.services.trading_controls import TradingControlState
from server.ws.hub import ConnectionHub

logger = logging.getLogger(__name__)
_SPA_RESERVED_PREFIXES = {"api", "ws"}
_DEFAULT_CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


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
        else configured_default
    )
    return _normalize_cors_allowed_origins(configured)


def _cors_allow_credentials(allowed_origins: list[str]) -> bool:
    # A wildcard origin is allowed only when explicitly configured. Disable
    # credentials in that mode so public examples do not ship a permissive
    # wildcard-plus-credentials CORS policy.
    return "*" not in allowed_origins


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


def _evaluate_controlled_session_pauses(state: AppState) -> dict[str, Any]:
    """Build fresh persisted gates and pause enabled sessions if required."""
    from server.composition.controlled_execution_services import (
        build_controlled_session_automatic_pause_orchestrator_service,
    )

    # The scheduler invokes this outside an HTTP request. Bind only the state
    # explicitly owned by its application while legacy route factories finish
    # migrating to constructor injection.
    with bind_app_state(state):
        return build_controlled_session_automatic_pause_orchestrator_service(
            state
        ).evaluate_all()


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
    state = app.state.app_state

    # ---- Startup ----
    from account_truth.broker_evidence import BrokerEvidenceRepository
    from account_truth.broker_statement_collector import (
        LocalBrokerStatementCollector,
        run_local_broker_statement_collector,
    )
    from core.event_bus import EventBus
    from notification.notifier import build_notifier
    from server.bootstrap import load_runtime_config
    from server.composition.ai_application_services import (
        build_strategy_research_write_service,
    )
    from server.config import BrokerStatementCollectorConfig, ServerConfig
    from server.services.ai_shadow_research_automation import (
        run_ai_shadow_research_automation_loop,
    )
    from server.services.daily_decision_evidence_automation import (
        DAILY_DECISION_EVIDENCE_AUTOMATION_TASK_NAME,
        run_daily_decision_evidence_automation_loop,
    )
    from server.services.decision_application import (
        run_batch_pre_trade_risk_for_state,
    )
    from server.services.market_calendar_automation import (
        run_market_calendar_automation_loop,
    )
    from server.services.market_refresh import refresh_one_quote
    from server.services.market_universe_automation import (
        run_market_universe_automation_loop,
    )
    from server.services.operations_projection import (
        current_decision_and_trading_plan,
    )

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
    try:
        db.publish_current_valuation_snapshot_sync()
    except Exception:
        logger.warning(
            "Failed to publish startup valuation snapshot; financial reads must fail closed",
            exc_info=True,
        )

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
        controlled_session_pause_runner=lambda: _evaluate_controlled_session_pauses(
            state
        ),
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

    collector_config = getattr(
        config,
        "broker_statement_collector",
        BrokerStatementCollectorConfig(),
    )
    broker_statement_collector = LocalBrokerStatementCollector(
        repository=(
            BrokerEvidenceRepository(db.path) if collector_config.enabled else None
        ),
        path=collector_config.path,
        enabled=collector_config.enabled,
        poll_interval_seconds=float(collector_config.poll_interval_seconds),
        stability_delay_seconds=float(collector_config.stability_delay_seconds),
        max_file_bytes=collector_config.max_file_bytes,
    )
    state.broker_statement_collector = broker_statement_collector
    app.state.broker_statement_collector = broker_statement_collector

    # 启动事件转发任务
    forward_task = asyncio.create_task(_forward_events(bridge, hub))
    broker_statement_collector_task: asyncio.Task[None] | None = None
    market_calendar_task: asyncio.Task[None] | None = None
    market_universe_task: asyncio.Task[None] | None = None
    decision_evidence_task: asyncio.Task[None] | None = None
    state.daily_decision_evidence_task = None
    shadow_research_task: asyncio.Task[None] | None = None
    if collector_config.enabled:
        broker_statement_collector_task = asyncio.create_task(
            run_local_broker_statement_collector(broker_statement_collector),
            name="local-broker-statement-collector",
        )
    # This loop is inert until an owner-authorized research-only policy exists.
    # It remains independent of live monitoring because it reads persisted
    # after-close evidence and has no execution authority.
    shadow_research_task = asyncio.create_task(
        run_ai_shadow_research_automation_loop(
            state=state,
            research_service_builder=lambda external: build_strategy_research_write_service(
                state,
                external=external,
            ),
        ),
        name="ai-shadow-research-automation",
    )

    # 自动启动实时监控
    if config.live_auto_start:
        scheduler.start()
        market_universe_task = asyncio.create_task(
            run_market_universe_automation_loop(db=db, config=config),
            name="market-universe-automation",
        )
        decision_evidence_task = asyncio.create_task(
            run_daily_decision_evidence_automation_loop(
                state=state,
                interval_seconds=config.live_poll_interval,
                plan_reader=current_decision_and_trading_plan,
                risk_runner=run_batch_pre_trade_risk_for_state,
                quote_refresher=refresh_one_quote,
            ),
            name=DAILY_DECISION_EVIDENCE_AUTOMATION_TASK_NAME,
        )
        state.daily_decision_evidence_task = decision_evidence_task
        if config.market_calendar_auto_sync:
            market_calendar_task = asyncio.create_task(
                run_market_calendar_automation_loop(db=db, config=config),
                name="market-calendar-automation",
            )

    logger.info("Karkinos Server started")

    yield

    # ---- Shutdown ----
    if shadow_research_task is not None:
        shadow_research_task.cancel()
        try:
            await shadow_research_task
        except asyncio.CancelledError:
            pass
    if decision_evidence_task is not None:
        decision_evidence_task.cancel()
        try:
            await decision_evidence_task
        except asyncio.CancelledError:
            pass
        finally:
            state.daily_decision_evidence_task = None
    if market_calendar_task is not None:
        market_calendar_task.cancel()
        try:
            await market_calendar_task
        except asyncio.CancelledError:
            pass
    if market_universe_task is not None:
        market_universe_task.cancel()
        try:
            await market_universe_task
        except asyncio.CancelledError:
            pass
    if broker_statement_collector_task is not None:
        broker_statement_collector_task.cancel()
        try:
            await broker_statement_collector_task
        except asyncio.CancelledError:
            pass
    forward_task.cancel()
    try:
        await forward_task
    except asyncio.CancelledError:
        pass

    scheduler.stop()
    bridge.stop()
    logger.info("Karkinos Server stopped")


def create_app(
    config_overrides: dict[str, Any] | None = None,
    *,
    runtime_config: Any | None = None,
) -> FastAPI:
    """创建 FastAPI 应用实例。"""
    effective_overrides = dict(config_overrides or {})
    if runtime_config is None:
        from server.bootstrap import load_runtime_config
        from server.config import ServerConfig

        runtime_config = load_runtime_config(ServerConfig, **effective_overrides)

    app = FastAPI(
        title="Karkinos Server",
        description="面向中国市场的个人量化投研与交易平台",
        version=__version__,
        lifespan=lifespan,
    )
    app_state = AppState()
    app.state.app_state = app_state
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
    app.add_middleware(AppStateContextMiddleware, app_state=app_state)

    from server.composition.router_registry import install_routers

    install_routers(app)

    # 挂载前端静态文件（生产构建）
    dist_dir = Path("web/dist")
    if dist_dir.exists():
        app.mount(
            "/", SPAStaticFiles(directory=str(dist_dir), html=True), name="static"
        )

    return app
