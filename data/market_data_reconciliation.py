"""Market data reconciliation helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

import pandas as pd

from core.types import AssetClass, BarFrequency, Symbol
from data.source import DataSource
from data.store import DataStore

_PRICE_COLUMNS = ("open", "high", "low", "close")
_VOLUME_COLUMNS = ("volume", "amount")


@dataclass(frozen=True)
class MarketBarMismatch:
    """One local-vs-provider market bar difference."""

    timestamp: str
    issue_type: str
    field: str | None = None
    local_value: float | None = None
    provider_value: float | None = None
    absolute_diff: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MarketBarReconciliationReport:
    """Auditable summary of local market bars compared with provider bars."""

    symbol: str
    frequency: str
    provider_name: str
    checked_at: str
    checked_rows: int
    local_rows: int
    provider_rows: int
    mismatch_count: int
    status: str
    mismatches: list[MarketBarMismatch]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["mismatches"] = [item.to_dict() for item in self.mismatches]
        return payload


def reconcile_market_bars(
    symbol: Symbol,
    frequency: BarFrequency,
    local_df: pd.DataFrame | None,
    provider_df: pd.DataFrame | None,
    *,
    provider_name: str,
    price_tolerance: float = 0.01,
    volume_tolerance: float = 1.0,
) -> MarketBarReconciliationReport:
    """Compare local cached market bars with freshly supplied provider bars."""
    local = _normalize_bars(local_df)
    provider = _normalize_bars(provider_df)
    local_dates = set(local.index)
    provider_dates = set(provider.index)
    shared_dates = sorted(local_dates & provider_dates)

    mismatches: list[MarketBarMismatch] = []
    for timestamp in shared_dates:
        local_row = local.loc[timestamp]
        provider_row = provider.loc[timestamp]
        for column in _PRICE_COLUMNS:
            mismatch = _compare_value(
                timestamp,
                column,
                local_row.get(column),
                provider_row.get(column),
                tolerance=price_tolerance,
            )
            if mismatch is not None:
                mismatches.append(mismatch)
        for column in _VOLUME_COLUMNS:
            if column not in local.columns and column not in provider.columns:
                continue
            mismatch = _compare_value(
                timestamp,
                column,
                local_row.get(column),
                provider_row.get(column),
                tolerance=volume_tolerance,
            )
            if mismatch is not None:
                mismatches.append(mismatch)

    for timestamp in sorted(local_dates - provider_dates):
        mismatches.append(
            MarketBarMismatch(timestamp=timestamp, issue_type="missing_provider_row")
        )
    for timestamp in sorted(provider_dates - local_dates):
        mismatches.append(
            MarketBarMismatch(timestamp=timestamp, issue_type="missing_local_row")
        )

    status = "matched" if not mismatches else "mismatched"
    if local.empty and not provider.empty:
        status = "missing_local"
    elif provider.empty and not local.empty:
        status = "missing_provider"

    return MarketBarReconciliationReport(
        symbol=str(symbol),
        frequency=frequency.value,
        provider_name=provider_name,
        checked_at=datetime.now().isoformat(),
        checked_rows=len(shared_dates),
        local_rows=len(local),
        provider_rows=len(provider),
        mismatch_count=len(mismatches),
        status=status,
        mismatches=mismatches,
    )


def reconcile_store_with_provider(
    store: DataStore,
    source: DataSource,
    symbol: Symbol,
    start: datetime,
    end: datetime,
    frequency: BarFrequency,
    *,
    provider_name: str,
    asset_class: AssetClass = AssetClass.STOCK,
    price_tolerance: float = 0.01,
    volume_tolerance: float = 1.0,
) -> MarketBarReconciliationReport:
    """Fetch provider bars and compare them with the local SQLite cache."""
    local = store.load_bars(symbol, frequency)
    local_slice = _slice_bars(local, start, end)
    provider = source.fetch_bars(symbol, start, end, frequency, asset_class)
    return reconcile_market_bars(
        symbol,
        frequency,
        local_slice,
        provider,
        provider_name=provider_name,
        price_tolerance=price_tolerance,
        volume_tolerance=volume_tolerance,
    )


def _normalize_bars(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty or "timestamp" not in df.columns:
        return pd.DataFrame().rename_axis("timestamp")

    normalized = df.copy()
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"]).dt.date.astype(
        str
    )
    normalized = normalized.drop_duplicates(subset=["timestamp"], keep="last")
    return normalized.set_index("timestamp").sort_index()


def _slice_bars(
    df: pd.DataFrame | None,
    start: datetime,
    end: datetime,
) -> pd.DataFrame | None:
    if df is None or df.empty or "timestamp" not in df.columns:
        return df
    normalized = df.copy()
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"])
    mask = (normalized["timestamp"] >= pd.Timestamp(start)) & (
        normalized["timestamp"] <= pd.Timestamp(end)
    )
    return normalized.loc[mask].reset_index(drop=True)


def _compare_value(
    timestamp: str,
    field: str,
    local_value,
    provider_value,
    *,
    tolerance: float,
) -> MarketBarMismatch | None:
    local_float = _optional_float(local_value)
    provider_float = _optional_float(provider_value)
    if local_float is None and provider_float is None:
        return None
    if local_float is None or provider_float is None:
        return MarketBarMismatch(
            timestamp=timestamp,
            issue_type="value_mismatch",
            field=field,
            local_value=local_float,
            provider_value=provider_float,
            absolute_diff=None,
        )
    diff = abs(local_float - provider_float)
    if diff <= tolerance:
        return None
    return MarketBarMismatch(
        timestamp=timestamp,
        issue_type="value_mismatch",
        field=field,
        local_value=local_float,
        provider_value=provider_float,
        absolute_diff=diff,
    )


def _optional_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
