"""Capability-based market data refresh contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Mapping, Sequence

from core.types import AssetClass, BarFrequency, Symbol
from data.market_data import MarketDataAdapter, MarketDataRecord


class MarketDataRefreshTrigger(Enum):
    """How a market-data refresh was requested."""

    MANUAL = "manual"
    SCHEDULED = "scheduled"

    @property
    def label_zh(self) -> str:
        return {
            MarketDataRefreshTrigger.MANUAL: "手动刷新",
            MarketDataRefreshTrigger.SCHEDULED: "定时刷新",
        }[self]


class MarketDataRefreshTaskKind(Enum):
    """Market data domains refreshed by v0.9 reliability flows."""

    INTRADAY_QUOTE = "intraday_quote"
    CLOSE_PRICE_BAR = "close_price_bar"
    FUND_NAV_CONFIRMATION = "fund_nav_confirmation"

    @property
    def label_zh(self) -> str:
        return {
            MarketDataRefreshTaskKind.INTRADAY_QUOTE: "盘中行情",
            MarketDataRefreshTaskKind.CLOSE_PRICE_BAR: "收盘价",
            MarketDataRefreshTaskKind.FUND_NAV_CONFIRMATION: "基金确认净值",
        }[self]


@dataclass(frozen=True)
class MarketDataRefreshTask:
    """One auditable market-data refresh task."""

    kind: MarketDataRefreshTaskKind
    trigger: MarketDataRefreshTrigger
    requested_at: datetime
    symbols: tuple[Symbol, ...]
    asset_class: AssetClass
    start: datetime
    end: datetime

    def to_payload(self) -> dict:
        return {
            "kind": self.kind.value,
            "kind_label_zh": self.kind.label_zh,
            "trigger": self.trigger.value,
            "trigger_label_zh": self.trigger.label_zh,
            "requested_at": self.requested_at.isoformat(),
            "symbols": [str(symbol) for symbol in self.symbols],
            "asset_class": self.asset_class.value,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


@dataclass(frozen=True)
class MarketDataRefreshTaskResult:
    """Result for one market-data refresh task."""

    task: MarketDataRefreshTask
    records: tuple[MarketDataRecord, ...]
    failed_symbols: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if self.failed_symbols and self.records:
            return "partial_success"
        if self.failed_symbols:
            return "failed"
        return "success"

    @property
    def refreshed_symbols(self) -> tuple[str, ...]:
        return tuple(sorted({str(record.symbol) for record in self.records}))

    def to_payload(self) -> dict:
        return {
            "task": self.task.to_payload(),
            "status": self.status,
            "record_count": len(self.records),
            "refreshed_symbols": list(self.refreshed_symbols),
            "failed_symbols": list(self.failed_symbols),
            "errors": list(self.errors),
            "records": [record.to_payload() for record in self.records],
        }


@dataclass(frozen=True)
class MarketDataRefreshRun:
    """Aggregate refresh evidence for manual or scheduled market-data updates."""

    trigger: MarketDataRefreshTrigger
    requested_at: datetime
    tasks: tuple[MarketDataRefreshTask, ...]
    task_results: tuple[MarketDataRefreshTaskResult, ...]
    trading_behavior_changed: bool = False
    broker_order_submission_enabled: bool = False
    manual_confirmation_required_unchanged: bool = True

    @property
    def status(self) -> str:
        statuses = {result.status for result in self.task_results}
        if not statuses or statuses == {"success"}:
            return "success"
        if "success" in statuses or "partial_success" in statuses:
            return "partial_success"
        return "failed"

    @property
    def total_records(self) -> int:
        return sum(len(result.records) for result in self.task_results)

    @property
    def refreshed_symbols(self) -> list[str]:
        return sorted(
            {
                symbol
                for result in self.task_results
                for symbol in result.refreshed_symbols
            }
        )

    @property
    def failed_symbols(self) -> list[str]:
        return sorted(
            {symbol for result in self.task_results for symbol in result.failed_symbols}
        )

    def to_payload(self) -> dict:
        return {
            "trigger": self.trigger.value,
            "trigger_label_zh": self.trigger.label_zh,
            "requested_at": self.requested_at.isoformat(),
            "status": self.status,
            "total_records": self.total_records,
            "refreshed_symbols": self.refreshed_symbols,
            "failed_symbols": self.failed_symbols,
            "tasks": [task.to_payload() for task in self.tasks],
            "task_results": [result.to_payload() for result in self.task_results],
            "safety": {
                "trading_behavior_changed": self.trading_behavior_changed,
                "broker_order_submission_enabled": (
                    self.broker_order_submission_enabled
                ),
                "manual_confirmation_required_unchanged": (
                    self.manual_confirmation_required_unchanged
                ),
            },
        }


def build_market_data_refresh_tasks(
    *,
    trigger: MarketDataRefreshTrigger,
    requested_at: datetime,
    symbols_by_asset_class: Mapping[AssetClass, Sequence[Symbol]],
    close_bar_lookback_days: int = 7,
) -> tuple[MarketDataRefreshTask, ...]:
    """Build refresh tasks without implying broker execution or trading approval."""
    close_start = requested_at - timedelta(days=close_bar_lookback_days)
    non_fund_symbols: list[tuple[AssetClass, tuple[Symbol, ...]]] = []
    fund_symbols: tuple[Symbol, ...] = ()
    for asset_class, symbols in symbols_by_asset_class.items():
        normalized = tuple(sorted(symbols, key=str))
        if not normalized:
            continue
        if asset_class is AssetClass.FUND:
            fund_symbols = normalized
            continue
        non_fund_symbols.append((asset_class, normalized))

    tasks: list[MarketDataRefreshTask] = []
    for asset_class, symbols in non_fund_symbols:
        tasks.append(
            MarketDataRefreshTask(
                kind=MarketDataRefreshTaskKind.INTRADAY_QUOTE,
                trigger=trigger,
                requested_at=requested_at,
                symbols=symbols,
                asset_class=asset_class,
                start=requested_at,
                end=requested_at,
            )
        )
    for asset_class, symbols in non_fund_symbols:
        tasks.append(
            MarketDataRefreshTask(
                kind=MarketDataRefreshTaskKind.CLOSE_PRICE_BAR,
                trigger=trigger,
                requested_at=requested_at,
                symbols=symbols,
                asset_class=asset_class,
                start=close_start,
                end=requested_at,
            )
        )
    if fund_symbols:
        tasks.append(
            MarketDataRefreshTask(
                kind=MarketDataRefreshTaskKind.FUND_NAV_CONFIRMATION,
                trigger=trigger,
                requested_at=requested_at,
                symbols=fund_symbols,
                asset_class=AssetClass.FUND,
                start=close_start,
                end=requested_at,
            )
        )
    return tuple(tasks)


def run_market_data_refresh(
    adapter: MarketDataAdapter,
    tasks: Sequence[MarketDataRefreshTask],
) -> MarketDataRefreshRun:
    """Run market-data refresh tasks and return audit evidence only."""
    task_results = tuple(_run_refresh_task(adapter, task) for task in tasks)
    trigger = tasks[0].trigger if tasks else MarketDataRefreshTrigger.MANUAL
    requested_at = tasks[0].requested_at if tasks else datetime.now().astimezone()
    return MarketDataRefreshRun(
        trigger=trigger,
        requested_at=requested_at,
        tasks=tuple(tasks),
        task_results=task_results,
    )


def _run_refresh_task(
    adapter: MarketDataAdapter,
    task: MarketDataRefreshTask,
) -> MarketDataRefreshTaskResult:
    records: list[MarketDataRecord] = []
    failed_symbols: list[str] = []
    errors: list[str] = []
    for symbol in task.symbols:
        try:
            records.extend(_fetch_records_for_task(adapter, task, symbol))
        except Exception as exc:
            failed_symbols.append(str(symbol))
            errors.append(f"{symbol}: {exc}")
    return MarketDataRefreshTaskResult(
        task=task,
        records=tuple(records),
        failed_symbols=tuple(failed_symbols),
        errors=tuple(errors),
    )


def _fetch_records_for_task(
    adapter: MarketDataAdapter,
    task: MarketDataRefreshTask,
    symbol: Symbol,
) -> list[MarketDataRecord]:
    if task.kind is MarketDataRefreshTaskKind.INTRADAY_QUOTE:
        return adapter.fetch_snapshot(symbol, task.asset_class)
    if task.kind is MarketDataRefreshTaskKind.CLOSE_PRICE_BAR:
        return adapter.fetch_daily_bars(
            symbol,
            task.start,
            task.end,
            task.asset_class,
        )
    if task.kind is MarketDataRefreshTaskKind.FUND_NAV_CONFIRMATION:
        return adapter.fetch_snapshot(symbol, AssetClass.FUND)
    raise ValueError(f"unsupported market data refresh task: {task.kind.value}")
