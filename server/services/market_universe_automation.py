"""Audited after-close ingestion for the full A-share research universe."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, time, timedelta
from time import sleep as default_sleep
from typing import Any, Callable

import pandas as pd

from core.types import AssetClass, BarFrequency, Symbol
from data.manager import DataManager, build_sources
from data.store import DataStore
from server.bootstrap import resolve_data_dir
from server.services.market_hours import get_shanghai_now
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    normalize_a_share_members,
    preliminary_research_panel_symbols,
    require_complete_market_universe_snapshot,
)

logger = logging.getLogger(__name__)

MARKET_UNIVERSE_AUTOMATION_SCHEMA_VERSION = "karkinos.market_universe_automation.v1"
MARKET_UNIVERSE_AUTOMATION_RUN_TYPE = "market_universe_sync"
MARKET_UNIVERSE_AUTOMATION_INTERVAL_SECONDS = 60 * 60
_POST_CLOSE_INGESTION_TIME = time(16, 0)


class MarketUniverseAutomationService:
    """Refresh and persist stock membership plus an overcomplete bar panel."""

    def __init__(
        self,
        *,
        db: Any,
        config: Any,
        data_store: DataStore | None = None,
        data_manager: DataManager | None = None,
        source: Any | None = None,
        policy: MarketUniversePolicy | None = None,
        throttle_seconds: float | None = None,
        sleep_fn: Callable[[float], None] = default_sleep,
    ) -> None:
        self._db = db
        self._config = config
        self._data_store = data_store or DataStore(resolve_data_dir())
        sources = None
        if data_manager is None or source is None:
            sources = build_sources(
                data_source=str(getattr(config, "data_source", "akshare")),
                tushare_token=str(getattr(config, "tushare_token", "") or ""),
            )
        self._source = source or sources[str(getattr(config, "data_source", "akshare"))]
        self._data_manager = data_manager or DataManager(
            sources=sources or {},
            store=self._data_store,
            default_source=str(getattr(config, "data_source", "akshare")),
        )
        self._policy = policy or MarketUniversePolicy()
        self._throttle_seconds = (
            _provider_request_interval_seconds(
                str(getattr(config, "data_source", "akshare"))
            )
            if throttle_seconds is None
            else float(throttle_seconds)
        )
        if self._throttle_seconds < 0:
            raise ValueError("market_universe_throttle_seconds_invalid")
        self._sleep = sleep_fn

    def run_due(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = get_shanghai_now(now)
        trade_date = _latest_verified_closed_trading_date(self._db, current)
        run_date = current.date().isoformat()
        provider_name = str(getattr(self._config, "data_source", "akshare"))
        if trade_date is None:
            return self._record_run(
                run_id=f"market_universe_sync:pending:{run_date}",
                run_date=run_date,
                status="blocked",
                now=current,
                payload={
                    **self._base_payload(provider_name),
                    "trade_date": None,
                    "blockers": ["verified_closed_trading_date_unavailable"],
                    "retryable": True,
                },
            )
        run_id = f"market_universe_sync:{provider_name}:{trade_date}"
        existing = self._db.get_automation_run_sync(run_id)
        if existing and str(existing.get("status")) == "completed":
            return existing

        try:
            snapshot = self._data_store.get_market_universe_snapshot(
                trade_date=trade_date
            )
            provider_contacted = False
            if snapshot is None:
                symbols = self._source.list_symbols()
                provider_contacted = True
                members = normalize_a_share_members(symbols)
                if len(members) < self._policy.minimum_master_member_count:
                    raise ValueError("market_universe_provider_result_incomplete")
                snapshot = self._data_store.save_market_universe_snapshot(
                    trade_date=trade_date,
                    provider_name=provider_name,
                    members=members,
                )
            snapshot = require_complete_market_universe_snapshot(
                snapshot,
                policy=self._policy,
                expected_trade_date=trade_date,
            )
            preliminary = preliminary_research_panel_symbols(
                snapshot,
                policy=self._policy,
            )
            start_date = _history_start(self._config, trade_date)
            updated = 0
            failed = 0
            ready = 0
            skipped_ready = 0
            remote_attempted = 0
            for symbol_text in preliminary:
                symbol = Symbol(symbol_text)
                if _persisted_window_ready(
                    self._data_store,
                    symbol=symbol,
                    start_date=start_date.isoformat(),
                    end_date=trade_date,
                    minimum_rows=self._policy.minimum_history_rows,
                ):
                    ready += 1
                    skipped_ready += 1
                    continue
                if self._throttle_seconds:
                    self._sleep(self._throttle_seconds)
                remote_attempted += 1
                try:
                    self._data_manager.get_bars(
                        symbol,
                        start=datetime.combine(start_date, time.min),
                        end=datetime.combine(
                            datetime.fromisoformat(trade_date).date(), time.min
                        ),
                        frequency=BarFrequency.DAILY,
                        asset_class=AssetClass.STOCK,
                        allow_remote_refresh=True,
                        refresh_ttl_seconds=0,
                        degrade_to_cache=False,
                    )
                    updated += 1
                except Exception:
                    failed += 1
                    logger.warning(
                        "Market-universe research-panel bar refresh failed for %s",
                        symbol_text,
                        exc_info=True,
                    )
                if _persisted_window_ready(
                    self._data_store,
                    symbol=symbol,
                    start_date=start_date.isoformat(),
                    end_date=trade_date,
                    minimum_rows=self._policy.minimum_history_rows,
                ):
                    ready += 1
            blockers: list[str] = []
            if ready < self._policy.panel_size:
                blockers.append("research_panel_persisted_bar_coverage_incomplete")
            status = "completed" if not blockers else "failed"
            return self._record_run(
                run_id=run_id,
                run_date=run_date,
                status=status,
                now=current,
                payload={
                    **self._base_payload(provider_name),
                    "trade_date": trade_date,
                    "market_universe_snapshot_id": snapshot["snapshot_id"],
                    "market_universe_member_count": snapshot["member_count"],
                    "preliminary_research_panel_count": len(preliminary),
                    "persisted_bar_ready_count": ready,
                    "persisted_bar_skipped_ready_count": skipped_ready,
                    "remote_bar_refresh_attempt_count": remote_attempted,
                    "bar_refresh_success_count": updated,
                    "bar_refresh_failure_count": failed,
                    "provider_request_interval_seconds": self._throttle_seconds,
                    "provider_contacted": provider_contacted or remote_attempted > 0,
                    "blockers": blockers,
                    "retryable": bool(blockers),
                },
            )
        except Exception as exc:
            logger.warning("Market-universe automation failed closed", exc_info=True)
            return self._record_run(
                run_id=run_id,
                run_date=run_date,
                status="failed",
                now=current,
                payload={
                    **self._base_payload(provider_name),
                    "trade_date": trade_date,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "retryable": True,
                },
            )

    def _base_payload(self, provider_name: str) -> dict[str, Any]:
        return {
            "schema_version": MARKET_UNIVERSE_AUTOMATION_SCHEMA_VERSION,
            "trigger": "server_background_market_data_ingestion",
            "provider": provider_name,
            "policy": self._policy.to_dict(),
            "asset_scope": ["stock"],
            "read_endpoints_contact_providers": False,
            "changes_account_truth": False,
            "changes_strategy_promotion": False,
            "creates_order": False,
            "changes_execution_authority": False,
            "changes_capital_authority": False,
        }

    def _record_run(
        self,
        *,
        run_id: str,
        run_date: str,
        status: str,
        now: datetime,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._db.upsert_automation_run_sync(
            {
                "run_id": run_id,
                "run_type": MARKET_UNIVERSE_AUTOMATION_RUN_TYPE,
                "run_date": run_date,
                "status": status,
                "execution_mode": "market_data_ingestion",
                "started_at": now.isoformat(),
                "finished_at": now.isoformat(),
                "source_ref": payload.get("market_universe_snapshot_id"),
                "payload": payload,
            }
        )


async def run_market_universe_automation_loop(
    *,
    db: Any,
    config: Any,
    interval_seconds: float = MARKET_UNIVERSE_AUTOMATION_INTERVAL_SECONDS,
) -> None:
    """Run the idempotent universe ingestion immediately and once per hour."""
    service = MarketUniverseAutomationService(db=db, config=config)
    while True:
        try:
            await asyncio.to_thread(service.run_due)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected market-universe automation failure")
        await asyncio.sleep(interval_seconds)


def _provider_request_interval_seconds(provider_name: str) -> float:
    """Leave capacity below TuShare's base 50 requests/minute ceiling."""
    return 2.0 if provider_name.strip().lower() == "tushare" else 0.0


def _latest_verified_closed_trading_date(db: Any, now: datetime) -> str | None:
    cutoff_date = now.date()
    if now.time() < _POST_CLOSE_INGESTION_TIME:
        cutoff_date -= timedelta(days=1)
    for year in (cutoff_date.year, cutoff_date.year - 1):
        row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=year)
        if not row or row.get("official_verification_status") != "verified":
            continue
        try:
            days = json.loads(str(row.get("days_json") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        candidates = sorted(
            str(day.get("date"))
            for day in days
            if isinstance(day, dict)
            and day.get("is_trading_day") is True
            and str(day.get("date") or "") <= cutoff_date.isoformat()
        )
        if candidates:
            return candidates[-1]
    return None


def _history_start(config: Any, trade_date: str):
    end = datetime.fromisoformat(trade_date).date()
    start = end - timedelta(days=540)
    configured = str(getattr(config, "start_date", "") or "").strip()
    if configured:
        try:
            start = min(start, datetime.fromisoformat(configured).date())
        except ValueError:
            pass
    return start


def _persisted_window_ready(
    data_store: DataStore,
    *,
    symbol: Symbol,
    start_date: str,
    end_date: str,
    minimum_rows: int,
) -> bool:
    frame = data_store.load_bars(symbol, BarFrequency.DAILY)
    if frame is None or frame.empty or "timestamp" not in frame.columns:
        return False
    timestamps = pd.to_datetime(frame["timestamp"])
    mask = (timestamps >= pd.Timestamp(start_date)) & (
        timestamps
        <= pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    )
    selected = timestamps.loc[mask].sort_values()
    return bool(
        len(selected) >= minimum_rows
        and selected.iloc[-1].date().isoformat() == end_date
    )
