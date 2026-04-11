"""Settings routes — /api/settings/*"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter

from server.models import LiveStatusResponse, SettingsResponse

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config.json")


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/settings", tags=["settings"])

    @r.get("", response_model=SettingsResponse)
    async def get_settings() -> SettingsResponse:
        """读取当前配置。"""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config
        return SettingsResponse(
            host=config.host,
            port=config.port,
            live_auto_start=config.live_auto_start,
            initial_cash=float(config.initial_cash),
            start_date=config.start_date,
            end_date=config.end_date,
            assets=config.assets,
            strategy=config.strategy,
            short_period=config.short_period,
            long_period=config.long_period,
            data_source=config.data_source,
            notification=config.notification,
            live_poll_interval=config.live_poll_interval,
        )

    @r.put("", response_model=SettingsResponse)
    async def update_settings(settings: SettingsResponse) -> SettingsResponse:
        """更新配置（写入 config.json）。"""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config

        # 更新 config 对象
        config.host = settings.host
        config.port = settings.port
        config.live_auto_start = settings.live_auto_start
        config.initial_cash = __import__("decimal").Decimal(str(settings.initial_cash))
        config.start_date = settings.start_date
        config.end_date = settings.end_date
        config.assets = settings.assets
        config.strategy = settings.strategy
        config.short_period = settings.short_period
        config.long_period = settings.long_period
        config.data_source = settings.data_source
        config.notification = settings.notification
        config.live_poll_interval = settings.live_poll_interval

        # 持久化到 config.json
        data = {
            "host": config.host,
            "port": config.port,
            "live_auto_start": config.live_auto_start,
            "initial_cash": str(config.initial_cash),
            "start_date": config.start_date,
            "end_date": config.end_date,
            "assets": config.assets,
            "strategy": config.strategy,
            "short_period": config.short_period,
            "long_period": config.long_period,
            "data_source": config.data_source,
            "notification": config.notification,
            "live_poll_interval": config.live_poll_interval,
        }
        _CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))

        return settings

    @r.post("/live/start", response_model=LiveStatusResponse)
    async def start_live() -> LiveStatusResponse:
        """启动实时监控。"""
        from server.app import get_app_state

        state = get_app_state()
        scheduler = state.scheduler
        if not scheduler.is_running:
            scheduler.start()
        return LiveStatusResponse(
            running=scheduler.is_running, market_open=scheduler.is_market_open
        )

    @r.post("/live/stop", response_model=LiveStatusResponse)
    async def stop_live() -> LiveStatusResponse:
        """停止实时监控。"""
        from server.app import get_app_state

        state = get_app_state()
        scheduler = state.scheduler
        if scheduler.is_running:
            scheduler.stop()
        return LiveStatusResponse(
            running=scheduler.is_running, market_open=scheduler.is_market_open
        )

    @r.get("/live/status", response_model=LiveStatusResponse)
    async def live_status() -> LiveStatusResponse:
        """查询实时监控状态。"""
        from server.app import get_app_state

        state = get_app_state()
        scheduler = state.scheduler
        return LiveStatusResponse(
            running=scheduler.is_running, market_open=scheduler.is_market_open
        )

    @r.post("/notification/test")
    async def test_notification() -> dict:
        """发送测试通知。"""
        from server.app import get_app_state

        state = get_app_state()
        notifier = state.notifier
        if notifier is None:
            return {"status": "error", "message": "No notifier configured"}

        try:
            notifier.send(
                title="MyQuant 测试通知",
                message="如果你看到这条消息，说明通知配置正确！",
            )
            return {"status": "ok", "message": "Test notification sent"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return r
