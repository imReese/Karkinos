"""Audited after-close ingestion for the full A-share research universe."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping, Sequence
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
    require_complete_market_universe_snapshot,
)

logger = logging.getLogger(__name__)

MARKET_UNIVERSE_AUTOMATION_SCHEMA_VERSION = "karkinos.market_universe_automation.v2"
MARKET_UNIVERSE_AUTOMATION_RUN_TYPE = "market_universe_sync"
MARKET_UNIVERSE_AUTOMATION_INTERVAL_SECONDS = 60 * 60
_POST_CLOSE_INGESTION_TIME = time(16, 0)


class MarketUniverseAutomationService:
    """Refresh and freeze the stock master plus full-market bar history."""

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
        run_id = f"market_universe_sync:v2:{provider_name}:{trade_date}"
        existing = self._db.get_automation_run_sync(run_id)
        if existing and str(existing.get("status")) == "completed":
            return existing

        stock_master_metadata_fetched = False
        stock_master_useful_name_count = 0
        instrument_metadata_persisted_count = 0
        symbol_metadata: Any = None
        try:
            snapshot = self._data_store.get_market_universe_snapshot(
                trade_date=trade_date
            )
            provider_contacted = False
            if snapshot is None:
                metadata_lister = getattr(self._source, "list_symbol_metadata", None)
                if callable(metadata_lister):
                    symbol_metadata = metadata_lister()
                if symbol_metadata is None:
                    symbols = self._source.list_symbols()
                else:
                    stock_master_metadata_fetched = True
                    symbols = [
                        item.get("symbol")
                        for item in symbol_metadata
                        if isinstance(item, Mapping)
                    ]
                provider_contacted = True
                members = normalize_a_share_members(symbols)
                if len(members) < self._policy.minimum_master_member_count:
                    raise ValueError("market_universe_provider_result_incomplete")
                if stock_master_metadata_fetched:
                    metadata_items = _useful_stock_master_metadata(
                        symbol_metadata or [],
                        members=members,
                        provider_name=provider_name,
                        fetched_at=current.isoformat(),
                        trade_date=trade_date,
                    )
                    stock_master_useful_name_count = len(metadata_items)
                    if metadata_items:
                        batch_upsert = getattr(
                            self._db, "upsert_instrument_metadata_batch_sync", None
                        )
                        if not callable(batch_upsert):
                            raise RuntimeError(
                                "instrument_metadata_batch_persistence_unavailable"
                            )
                        instrument_metadata_persisted_count = int(
                            batch_upsert(metadata_items)
                        )
                        if instrument_metadata_persisted_count != len(metadata_items):
                            raise RuntimeError(
                                "instrument_metadata_batch_persistence_incomplete"
                            )
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
            members = [str(member["symbol"]) for member in snapshot["members"]]
            start_date = _history_start(self._config, trade_date)
            trading_dates = verified_trading_dates(
                self._db,
                start_date=start_date.isoformat(),
                end_date=trade_date,
            )
            if len(trading_dates) < self._policy.minimum_history_rows:
                raise ValueError("verified_market_history_window_incomplete")
            updated = 0
            failed = 0
            remote_attempted = 0
            receipt_skipped = 0
            batch_fetcher = getattr(self._source, "fetch_market_daily_bars", None)
            if callable(batch_fetcher):
                member_set = set(members)
                for market_date in trading_dates:
                    receipt = self._data_store.get_market_daily_ingestion_receipt(
                        trade_date=market_date,
                        provider_name=provider_name,
                    )
                    if receipt is not None:
                        receipt_skipped += 1
                        continue
                    if self._throttle_seconds:
                        self._sleep(self._throttle_seconds)
                    remote_attempted += 1
                    try:
                        frame = batch_fetcher(market_date)
                        frame = frame.loc[
                            frame["symbol"].astype(str).isin(member_set)
                        ].copy()
                        if frame.empty:
                            raise ValueError("market_daily_batch_no_active_members")
                        self._data_store.ingest_market_daily_batch(
                            trade_date=market_date,
                            provider_name=provider_name,
                            bars=frame,
                        )
                        updated += 1
                    except Exception:
                        failed += 1
                        logger.warning(
                            "Full-market daily batch refresh failed for %s",
                            market_date,
                            exc_info=True,
                        )
                        break
            else:
                for symbol_text in members:
                    symbol = Symbol(symbol_text)
                    if _persisted_window_ready(
                        self._data_store,
                        symbol=symbol,
                        start_date=start_date.isoformat(),
                        end_date=trade_date,
                        minimum_rows=self._policy.minimum_history_rows,
                    ):
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
                            "Full-market per-symbol bar refresh failed for %s",
                            symbol_text,
                            exc_info=True,
                        )
                if not failed:
                    _freeze_persisted_market_dates(
                        data_store=self._data_store,
                        provider_name=provider_name,
                        symbols=members,
                        start_date=start_date.isoformat(),
                        end_date=trade_date,
                        trading_dates=trading_dates,
                    )

            receipts = self._data_store.list_market_daily_ingestion_receipts(
                start_date=start_date.isoformat(),
                end_date=trade_date,
                provider_name=provider_name,
            )
            receipt_dates = {str(item["trade_date"]) for item in receipts}
            frames = self._data_store.load_market_bar_windows(
                symbols=members,
                start_date=start_date.isoformat(),
                end_date=trade_date,
            )
            ready = sum(
                1
                for frame in frames.values()
                if _frame_window_ready(
                    frame,
                    end_date=trade_date,
                    minimum_rows=self._policy.minimum_history_rows,
                )
            )
            blockers: list[str] = []
            missing_receipt_dates = sorted(set(trading_dates) - receipt_dates)
            if missing_receipt_dates:
                blockers.append("full_market_daily_receipt_coverage_incomplete")
            end_receipt = next(
                (
                    item
                    for item in receipts
                    if str(item.get("trade_date") or "") == trade_date
                ),
                {},
            )
            end_cross_section_count = int(end_receipt.get("row_count") or 0)
            minimum_end_cross_section_count = max(
                self._policy.panel_size,
                int(len(members) * 0.9),
            )
            minimum_ready_count = max(
                self._policy.panel_size,
                int(len(members) * 0.8),
            )
            if end_cross_section_count < minimum_end_cross_section_count:
                blockers.append("full_market_latest_cross_section_incomplete")
            if ready < minimum_ready_count:
                blockers.append("full_market_persisted_bar_coverage_incomplete")
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
                    "verified_history_start_date": start_date.isoformat(),
                    "verified_trading_date_count": len(trading_dates),
                    "full_market_daily_receipt_count": len(receipts),
                    "full_market_missing_receipt_dates": missing_receipt_dates[:100],
                    "full_market_missing_receipt_date_count": len(
                        missing_receipt_dates
                    ),
                    "persisted_bar_ready_count": ready,
                    "persisted_bar_excluded_count": len(members) - ready,
                    "minimum_persisted_bar_ready_count": minimum_ready_count,
                    "latest_cross_section_row_count": end_cross_section_count,
                    "minimum_latest_cross_section_row_count": (
                        minimum_end_cross_section_count
                    ),
                    "persisted_receipt_skipped_count": receipt_skipped,
                    "remote_bar_refresh_attempt_count": remote_attempted,
                    "bar_refresh_success_count": updated,
                    "bar_refresh_failure_count": failed,
                    "provider_request_interval_seconds": self._throttle_seconds,
                    "provider_contacted": provider_contacted or remote_attempted > 0,
                    "stock_master_metadata_fetched": stock_master_metadata_fetched,
                    "stock_master_useful_name_count": (stock_master_useful_name_count),
                    "instrument_metadata_persisted_count": (
                        instrument_metadata_persisted_count
                    ),
                    "full_market_history_frozen": not missing_receipt_dates,
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
                    "stock_master_metadata_fetched": stock_master_metadata_fetched,
                    "stock_master_useful_name_count": (stock_master_useful_name_count),
                    "instrument_metadata_persisted_count": (
                        instrument_metadata_persisted_count
                    ),
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


def _useful_stock_master_metadata(
    rows: Sequence[Mapping[str, Any]],
    *,
    members: Sequence[Mapping[str, Any]],
    provider_name: str,
    fetched_at: str,
    trade_date: str,
) -> list[dict[str, Any]]:
    member_by_symbol = {
        str(member.get("symbol") or "").strip(): member
        for member in members
        if str(member.get("symbol") or "").strip()
    }
    normalized: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().split(".", maxsplit=1)[0]
        display_name = str(row.get("display_name") or "").strip()
        member = member_by_symbol.get(symbol)
        if (
            member is None
            or not display_name
            or display_name == symbol
            or display_name == f"{symbol} A股"
        ):
            continue
        normalized[symbol] = {
            "symbol": symbol,
            "asset_type": "stock",
            "display_name": display_name,
            "provider_symbol": str(row.get("provider_symbol") or symbol),
            "exchange": member.get("exchange"),
            "market": "cn",
            "provider_name": provider_name,
            "source": "market_universe_stock_master",
            "fetched_at": fetched_at,
            "metadata": {
                "stock_master_trade_date": trade_date,
                "listing_status": member.get("listing_status"),
                "board": member.get("board"),
            },
        }
    return [normalized[symbol] for symbol in sorted(normalized)]


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


def verified_trading_dates(
    db: Any,
    *,
    start_date: str,
    end_date: str,
) -> list[str]:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    dates: set[str] = set()
    for year in range(start.year, end.year + 1):
        row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=year)
        if not row or row.get("official_verification_status") != "verified":
            continue
        try:
            days = json.loads(str(row.get("days_json") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        dates.update(
            str(day.get("date"))
            for day in days
            if isinstance(day, dict)
            and day.get("is_trading_day") is True
            and start_date <= str(day.get("date") or "") <= end_date
        )
    return sorted(dates)


def _freeze_persisted_market_dates(
    *,
    data_store: DataStore,
    provider_name: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    trading_dates: list[str],
) -> None:
    frames = data_store.load_market_bar_windows(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
    )
    rows_by_date: dict[str, list[pd.DataFrame]] = {
        market_date: [] for market_date in trading_dates
    }
    for symbol, frame in frames.items():
        dated = frame.copy()
        dated["trade_date"] = pd.to_datetime(dated["timestamp"]).dt.date.map(
            lambda value: value.isoformat()
        )
        for market_date, selected in dated.groupby("trade_date", sort=False):
            if market_date not in rows_by_date:
                continue
            batch = selected.drop(columns=["trade_date"]).copy()
            batch["symbol"] = symbol
            rows_by_date[market_date].append(batch)
    for market_date in trading_dates:
        existing = data_store.get_market_daily_ingestion_receipt(
            trade_date=market_date,
            provider_name=provider_name,
        )
        if existing is not None:
            continue
        parts = rows_by_date[market_date]
        if not parts:
            raise ValueError(f"persisted_market_date_missing:{market_date}")
        data_store.ingest_market_daily_batch(
            trade_date=market_date,
            provider_name=provider_name,
            bars=pd.concat(parts, ignore_index=True),
        )


def _frame_window_ready(
    frame: pd.DataFrame,
    *,
    end_date: str,
    minimum_rows: int,
) -> bool:
    if frame is None or frame.empty or "timestamp" not in frame.columns:
        return False
    timestamps = pd.to_datetime(frame["timestamp"]).sort_values()
    return bool(
        len(timestamps) >= minimum_rows
        and timestamps.iloc[-1].date().isoformat() == end_date
    )


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
