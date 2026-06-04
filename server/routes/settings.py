"""Settings routes — /api/settings/*"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from server.models import (
    AssetMetadataStatusResponse,
    DataSourceSettingsUpdate,
    DataSourceStatusResponse,
    LiveStatusResponse,
    SettingsResponse,
)
from server.services.asset_metadata import (
    build_asset_metadata_status,
    iter_configured_asset_metadata,
    metadata_configured_count,
)

logger = logging.getLogger(__name__)

_MASK = "****"


def _mask_token(token: str) -> str:
    if not token:
        return ""
    return f"{_MASK}{token[-4:]}" if len(token) > 4 else _MASK


def _provider_requires_token(provider_name: str) -> bool:
    return provider_name == "tushare"


def _provider_configured(config, provider_name: str) -> bool:
    if _provider_requires_token(provider_name):
        return bool(getattr(config, "tushare_token", ""))
    return provider_name in {"akshare", "tushare"}


def _provider_supports_funds(provider_name: str) -> bool | None:
    if provider_name == "akshare":
        return True
    if provider_name == "tushare":
        return False
    return None


def _has_fund_assets(config) -> bool:
    return any(
        str(asset.get("asset_class", "")).lower() in {"fund", "etf"}
        for asset in iter_configured_asset_metadata(SimpleState(config))
    )


class SimpleState:
    def __init__(self, config) -> None:
        self.config = config


def _settings_assets_payload(config) -> list[dict]:
    return [
        {key: value for key, value in asset.items() if key != "source"}
        for asset in iter_configured_asset_metadata(SimpleState(config))
    ]


def _settings_response(config) -> SettingsResponse:
    return SettingsResponse(
        host=config.host,
        port=config.port,
        live_auto_start=config.live_auto_start,
        initial_cash=float(config.initial_cash),
        start_date=config.start_date,
        end_date=config.end_date,
        assets=_settings_assets_payload(config),
        strategy=config.strategy,
        short_period=config.short_period,
        long_period=config.long_period,
        data_source=config.data_source,
        tushare_token=_mask_token(config.tushare_token),
        notification=config.notification,
        live_poll_interval=config.live_poll_interval,
    )


def _data_source_next_action(
    *,
    provider_name: str,
    provider_configured: bool,
    provider_supports_funds: bool | None,
    has_funds: bool,
    metadata_count: int,
) -> str | None:
    if not provider_configured:
        return "configure_data_source_token"
    if has_funds and provider_supports_funds is False:
        return "switch_to_fund_supported_provider"
    if metadata_count == 0:
        return "configure_asset_metadata"
    return None


def _build_data_source_status(state) -> DataSourceStatusResponse:
    config = state.config
    provider_name = str(getattr(config, "data_source", "akshare") or "akshare")
    provider_configured = _provider_configured(config, provider_name)
    provider_supports_funds = _provider_supports_funds(provider_name)
    metadata_count = metadata_configured_count(state)
    persistent_timestamps: list[str] = []
    db = getattr(state, "db", None)
    if db is not None and hasattr(db, "get_latest_quotes_sync"):
        for row in db.get_latest_quotes_sync():
            timestamp = row.get("timestamp")
            if timestamp:
                persistent_timestamps.append(str(timestamp))
    has_persistent_cache = bool(persistent_timestamps)
    return DataSourceStatusResponse(
        data_source=provider_name,
        provider_name=provider_name,
        provider_configured=provider_configured,
        provider_supports_funds=provider_supports_funds,
        provider_requires_token=_provider_requires_token(provider_name),
        requires_restart=False,
        next_action=_data_source_next_action(
            provider_name=provider_name,
            provider_configured=provider_configured,
            provider_supports_funds=provider_supports_funds,
            has_funds=_has_fund_assets(config),
            metadata_count=metadata_count,
        ),
        metadata_configured_count=metadata_count,
        has_persistent_cache=has_persistent_cache,
        latest_persistent_quote_timestamp=max(persistent_timestamps)
        if persistent_timestamps
        else None,
        persistent_cache_status="available" if has_persistent_cache else "missing",
    )


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/settings", tags=["settings"])

    @r.get("", response_model=SettingsResponse)
    async def get_settings() -> SettingsResponse:
        """读取当前配置。"""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config
        return _settings_response(config)

    @r.put("", response_model=SettingsResponse)
    async def update_settings(settings: SettingsResponse) -> SettingsResponse:
        """Update in-memory runtime settings without writing config.json."""
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
        # tushare_token 条件更新：非脱敏值才写入
        new_token = settings.tushare_token
        if not new_token.startswith(_MASK):
            config.tushare_token = new_token
        config.notification = settings.notification
        config.live_poll_interval = settings.live_poll_interval

        return _settings_response(config)

    @r.get("/data-source", response_model=DataSourceStatusResponse)
    async def get_data_source_settings() -> DataSourceStatusResponse:
        """读取当前数据源能力与本地切换状态。"""
        from server.app import get_app_state

        return _build_data_source_status(get_app_state())

    @r.get("/asset-metadata", response_model=AssetMetadataStatusResponse)
    async def get_asset_metadata_status() -> AssetMetadataStatusResponse:
        """读取资产元数据配置覆盖情况与缺失模板。"""
        from server.app import get_app_state

        return AssetMetadataStatusResponse(**build_asset_metadata_status(get_app_state()))

    @r.put("/data-source", response_model=SettingsResponse)
    async def update_data_source_settings(
        payload: DataSourceSettingsUpdate,
    ) -> SettingsResponse:
        """Update in-memory data-source settings without writing config.json."""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config

        config.data_source = payload.data_source
        if not payload.tushare_token.startswith(_MASK):
            config.tushare_token = payload.tushare_token
        config.live_poll_interval = payload.live_poll_interval

        return _settings_response(config)

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
                title="Karkinos 测试通知",
                message="如果你看到这条消息，说明通知配置正确！",
            )
            return {"status": "ok", "message": "Test notification sent"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return r
