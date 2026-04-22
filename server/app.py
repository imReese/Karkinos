"""FastAPI app factory + lifespan。"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from server.bridge import EventBusBridge
from server.db import AppDatabase
from server.scheduler import TradingScheduler
from server.ws.hub import ConnectionHub

logger = logging.getLogger(__name__)


def _env_flag(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


class AppState:
    """全局应用状态，供路由通过 get_app_state() 访问。"""

    def __init__(self) -> None:
        self.config: Any = None
        self.db: AppDatabase | None = None
        self.hub: ConnectionHub | None = None
        self.bridge: EventBusBridge | None = None
        self.scheduler: TradingScheduler | None = None
        self.notifier: Any = None


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


class SPAStaticFiles(StaticFiles):
    """StaticFiles with SPA index fallback for client-side routes."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code != 404:
            return response

        requested = Path(path)
        if requested.suffix:
            return response

        return await super().get_response("index.html", scope)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    global _app_state

    state = get_app_state()

    # ---- Startup ----
    from config import ServerConfig
    from core.event_bus import EventBus
    from notification.notifier import build_notifier
    from server.bootstrap import load_runtime_config

    # 加载配置
    config_overrides = getattr(app.state, "config_overrides", {})
    config = load_runtime_config(ServerConfig, **config_overrides)
    state.config = config

    # 初始化数据库
    db = AppDatabase()
    await db.init()
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

    # 初始化调度器
    scheduler = TradingScheduler(config, bridge, notifier, db=db)
    state.scheduler = scheduler

    # 存储到 app.state
    app.state.config = config
    app.state.db = db
    app.state.hub = hub
    app.state.bridge = bridge
    app.state.scheduler = scheduler
    app.state.notifier = notifier

    # 启动事件转发任务
    forward_task = asyncio.create_task(_forward_events(bridge, hub))

    # 自动启动实时监控
    if config.live_auto_start:
        scheduler.start()

    logger.info("MyQuant Server started")

    yield

    # ---- Shutdown ----
    forward_task.cancel()
    try:
        await forward_task
    except asyncio.CancelledError:
        pass

    scheduler.stop()
    bridge.stop()
    logger.info("MyQuant Server stopped")


def create_app(config_overrides: dict[str, Any] | None = None) -> FastAPI:
    """创建 FastAPI 应用实例。"""
    effective_overrides = dict(config_overrides or {})
    env_live_auto_start = _env_flag("MYQUANT_LIVE_AUTO_START")
    if env_live_auto_start is not None:
        effective_overrides.setdefault("live_auto_start", env_live_auto_start)

    app = FastAPI(
        title="MyQuant Server",
        description="个人量化交易辅助系统",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.config_overrides = effective_overrides

    # CORS — 开发环境允许所有来源
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    from server.routes.backtest import create_router as backtest_router
    from server.routes.ledger import create_router as ledger_router
    from server.routes.market import create_router as market_router
    from server.routes.portfolio import create_router as portfolio_router
    from server.routes.settings import create_router as settings_router
    from server.routes.signals import create_router as signals_router
    from server.ws.handlers import router as ws_router

    app.include_router(market_router())
    app.include_router(ledger_router())
    app.include_router(portfolio_router())
    app.include_router(signals_router())
    app.include_router(backtest_router())
    app.include_router(settings_router())
    app.include_router(ws_router)

    # 挂载前端静态文件（生产构建）
    dist_dir = Path("web/dist")
    if dist_dir.exists():
        app.mount("/", SPAStaticFiles(directory=str(dist_dir), html=True), name="static")

    return app
