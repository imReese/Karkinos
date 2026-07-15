"""Settings routes — /api/settings/*"""

from __future__ import annotations

import json
import logging
from dataclasses import is_dataclass, replace
from decimal import Decimal

from fastapi import APIRouter, HTTPException

from notification.notifier import notification_configuration_status
from server.bootstrap import resolve_config_path
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


def _provider_requires_token(provider_name: str) -> bool:
    return provider_name == "tushare"


def _require_configured_provider_credential(provider_name: str, config) -> None:
    if provider_name == "tushare" and not config.tushare_token:
        raise HTTPException(
            status_code=422,
            detail=(
                "TUSHARE_TOKEN is not configured; set it in the selected "
                "environment file and restart Karkinos before enabling TuShare"
            ),
        )


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


def _has_fund_assets(state) -> bool:
    return any(
        str(asset.get("asset_class", "")).lower() in {"fund", "etf"}
        for asset in _settings_assets_payload(state)
    )


class SimpleState:
    def __init__(self, config) -> None:
        self.config = config


def _settings_assets_payload(state) -> list[dict]:
    db = getattr(state, "db", None)
    list_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    if callable(list_watchlist):
        rows = list_watchlist() or []
        return [
            {
                "symbol": str(row.get("symbol") or ""),
                "asset_class": str(row.get("asset_class") or "stock"),
                "display_name": str(row.get("display_name") or row.get("symbol") or ""),
                "source": row.get("source") or "db",
            }
            for row in rows
            if str(row.get("symbol") or "").strip()
        ]
    return [
        {key: value for key, value in asset.items() if key != "source"}
        for asset in iter_configured_asset_metadata(
            SimpleState(getattr(state, "config", None))
        )
    ]


def _settings_response(state) -> SettingsResponse:
    config = state.config
    account_rate, account_minimum = _account_cost_settings(config)
    return SettingsResponse(
        host=config.host,
        port=config.port,
        live_auto_start=config.live_auto_start,
        initial_cash=float(config.initial_cash),
        start_date=config.start_date,
        end_date=config.end_date,
        assets=_settings_assets_payload(state),
        strategy=config.strategy,
        short_period=config.short_period,
        long_period=config.long_period,
        data_source=config.data_source,
        tushare_token_configured=bool(config.tushare_token),
        notification=notification_configuration_status(config.notification),
        live_poll_interval=config.live_poll_interval,
        account_commission_rate=float(account_rate),
        account_min_commission=float(account_minimum),
    )


def _account_cost_settings(config) -> tuple[Decimal, Decimal]:
    schedule = getattr(config, "broker_fee_schedule", None)
    rate = getattr(schedule, "stock_a_commission_rate", None)
    minimum = getattr(schedule, "stock_a_min_commission", None)
    return (
        Decimal(
            str(
                rate
                if rate is not None
                else getattr(config, "account_commission_rate", 0.0001)
            )
        ),
        Decimal(
            str(
                minimum
                if minimum is not None
                else getattr(config, "account_min_commission", 5)
            )
        ),
    )


def _set_account_cost_settings(config, rate: Decimal, minimum: Decimal) -> None:
    config.account_commission_rate = rate
    config.account_min_commission = minimum
    schedule = getattr(config, "broker_fee_schedule", None)
    if schedule is None:
        return
    if is_dataclass(schedule):
        config.broker_fee_schedule = replace(
            schedule,
            stock_a_commission_rate=rate,
            stock_a_min_commission=minimum,
        )
        return
    try:
        schedule.stock_a_commission_rate = rate
        schedule.stock_a_min_commission = minimum
    except AttributeError:
        logger.debug("broker fee schedule object is immutable; keeping legacy aliases")


def _json_number(value: Decimal | float | int | str) -> float:
    return float(Decimal(str(value)))


def _read_persisted_config() -> dict:
    config_path = resolve_config_path()
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_persisted_config(persisted: dict) -> None:
    config_path = resolve_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(persisted, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _persist_runtime_config(
    updates: dict,
    *,
    remove_fields: tuple[str, ...] = (),
) -> None:
    persisted = _read_persisted_config()
    raw_data_source = persisted.get("data_source")
    if isinstance(raw_data_source, dict):
        data_source = dict(raw_data_source)
    else:
        data_source = (
            {"provider": raw_data_source} if raw_data_source is not None else {}
        )
    data_source.pop("tushare_token", None)
    persisted.pop("tushare_token", None)
    if "live_poll_interval" in persisted:
        data_source["live_poll_interval"] = persisted.pop("live_poll_interval")

    for field in remove_fields:
        if field in {"data_source", "live_poll_interval"}:
            grouped_field = "provider" if field == "data_source" else field
            data_source.pop(grouped_field, None)
        else:
            persisted.pop(field, None)
    for field, value in updates.items():
        if field in {"data_source", "live_poll_interval"}:
            grouped_field = "provider" if field == "data_source" else field
            data_source[grouped_field] = value
        else:
            persisted[field] = value
    persisted["data_source"] = data_source
    _write_persisted_config(persisted)


def _persist_account_cost_settings(config) -> None:
    rate, minimum = _account_cost_settings(config)
    persisted = _read_persisted_config()
    raw_schedule = persisted.get("broker_fee")
    if not isinstance(raw_schedule, dict):
        raw_schedule = persisted.get("broker_fee_schedule")
    schedule = dict(raw_schedule) if isinstance(raw_schedule, dict) else {}
    schedule.update(
        {
            "stock_a_commission_rate": _json_number(rate),
            "stock_a_min_commission": _json_number(minimum),
        }
    )
    persisted.pop("account_commission_rate", None)
    persisted.pop("account_min_commission", None)
    persisted.pop("broker_fee_schedule", None)
    persisted["broker_fee"] = schedule
    _write_persisted_config(persisted)


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
            has_funds=_has_fund_assets(state),
            metadata_count=metadata_count,
        ),
        metadata_configured_count=metadata_count,
        has_persistent_cache=has_persistent_cache,
        latest_persistent_quote_timestamp=(
            max(persistent_timestamps) if persistent_timestamps else None
        ),
        persistent_cache_status="available" if has_persistent_cache else "missing",
    )


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/settings", tags=["settings"])

    @r.get("", response_model=SettingsResponse)
    async def get_settings() -> SettingsResponse:
        """读取当前配置。"""
        from server.app import get_app_state

        state = get_app_state()
        return _settings_response(state)

    @r.put("", response_model=SettingsResponse)
    async def update_settings(settings: SettingsResponse) -> SettingsResponse:
        """Update runtime settings and persist account commission rules."""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config

        _require_configured_provider_credential(settings.data_source, config)

        # 更新 config 对象
        config.host = settings.host
        config.port = settings.port
        config.live_auto_start = settings.live_auto_start
        config.initial_cash = __import__("decimal").Decimal(str(settings.initial_cash))
        config.start_date = settings.start_date
        config.end_date = settings.end_date
        config.strategy = settings.strategy
        config.short_period = settings.short_period
        config.long_period = settings.long_period
        config.data_source = settings.data_source
        config.live_poll_interval = settings.live_poll_interval
        _set_account_cost_settings(
            config,
            Decimal(str(settings.account_commission_rate)),
            Decimal(str(settings.account_min_commission)),
        )
        _persist_account_cost_settings(config)

        return _settings_response(state)

    @r.get("/data-source", response_model=DataSourceStatusResponse)
    async def get_data_source_settings() -> DataSourceStatusResponse:
        """读取当前数据源能力与本地切换状态。"""
        from server.app import get_app_state

        return _build_data_source_status(get_app_state())

    @r.get("/asset-metadata", response_model=AssetMetadataStatusResponse)
    async def get_asset_metadata_status() -> AssetMetadataStatusResponse:
        """读取资产元数据配置覆盖情况与缺失模板。"""
        from server.app import get_app_state

        return AssetMetadataStatusResponse(
            **build_asset_metadata_status(get_app_state())
        )

    @r.put("/data-source", response_model=SettingsResponse)
    async def update_data_source_settings(
        payload: DataSourceSettingsUpdate,
    ) -> SettingsResponse:
        """Update data-source runtime settings and persist local config."""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config

        _require_configured_provider_credential(payload.data_source, config)
        config.data_source = payload.data_source
        config.live_poll_interval = payload.live_poll_interval
        updates = {
            "data_source": config.data_source,
            "live_poll_interval": config.live_poll_interval,
        }
        _persist_runtime_config(updates)

        return _settings_response(state)

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
        notification_status = notification_configuration_status(
            state.config.notification
        )
        if not notification_status["configured"]:
            return {
                "status": "error",
                "message": "Notification environment credentials are missing",
            }

        try:
            notifier.send(
                title="Karkinos 测试通知",
                message="如果你看到这条消息，说明通知配置正确！",
            )
            return {"status": "ok", "message": "Test notification sent"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return r
