"""Market data reliability contracts for Karkinos v0.9."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Protocol, Sequence

from core.types import AssetClass, BarFrequency, Symbol


class MarketDataStatus(Enum):
    """Shared status vocabulary for market data reliability."""

    CONFIRMED = "confirmed"
    LIVE = "live"
    CACHE = "cache"
    ESTIMATED = "estimated"
    MISSING = "missing"
    STALE = "stale"
    CONFIRMED_NAV_MISSING = "confirmed_nav_missing"

    @property
    def label_zh(self) -> str:
        return {
            MarketDataStatus.CONFIRMED: "已确认",
            MarketDataStatus.LIVE: "实时行情",
            MarketDataStatus.CACHE: "缓存行情",
            MarketDataStatus.ESTIMATED: "估算中",
            MarketDataStatus.MISSING: "缺失",
            MarketDataStatus.STALE: "已过期",
            MarketDataStatus.CONFIRMED_NAV_MISSING: "确认净值缺失",
        }[self]

    @property
    def is_confirmed(self) -> bool:
        return self is MarketDataStatus.CONFIRMED

    @property
    def can_be_presented_as_confirmed(self) -> bool:
        return self is MarketDataStatus.CONFIRMED


class MarketDataEventKind(Enum):
    """Normalized market data event types."""

    DAILY_BAR = "daily_bar"
    INTRADAY_BAR = "intraday_bar"
    SNAPSHOT = "snapshot"
    TICK = "tick"
    REPLAY = "replay"


class MarketDataQualityStatus(Enum):
    """Aggregate quality state for a market-data evidence set."""

    PASS = "pass"
    DEGRADED = "degraded"
    BLOCKED = "blocked"

    @property
    def label_zh(self) -> str:
        return {
            MarketDataQualityStatus.PASS: "通过",
            MarketDataQualityStatus.DEGRADED: "降级",
            MarketDataQualityStatus.BLOCKED: "阻断",
        }[self]


class MarketDataDiagnosticSeverity(Enum):
    """Severity for a market-data diagnostic finding."""

    WARNING = "warning"
    BLOCKING = "blocking"

    @property
    def label_zh(self) -> str:
        return {
            MarketDataDiagnosticSeverity.WARNING: "警告",
            MarketDataDiagnosticSeverity.BLOCKING: "阻断",
        }[self]


class MarketDataDiagnosticKind(Enum):
    """Deterministic diagnostic categories for market data quality."""

    MISSING_TRADING_DATE = "missing_trading_date"
    NON_TRADING_DAY_OBSERVATION = "non_trading_day_observation"
    STALE_QUOTE = "stale_quote"
    DELAYED_FUND_NAV = "delayed_fund_nav"
    ADJUSTMENT_GAP = "adjustment_gap"
    PROVIDER_DIFFERENCE = "provider_difference"


_STATUS_ALIASES = {
    "confirmed": MarketDataStatus.CONFIRMED,
    "fresh": MarketDataStatus.CONFIRMED,
    "ok": MarketDataStatus.CONFIRMED,
    "live": MarketDataStatus.LIVE,
    "cache": MarketDataStatus.CACHE,
    "cached": MarketDataStatus.CACHE,
    "cache_only": MarketDataStatus.CACHE,
    "estimated": MarketDataStatus.ESTIMATED,
    "estimate": MarketDataStatus.ESTIMATED,
    "missing": MarketDataStatus.MISSING,
    "unavailable": MarketDataStatus.MISSING,
    "stale": MarketDataStatus.STALE,
    "quote_older_than_expected_session": MarketDataStatus.STALE,
    "market_closed_cache_only": MarketDataStatus.CACHE,
    "confirmed_nav_missing": MarketDataStatus.CONFIRMED_NAV_MISSING,
    "confirmed nav missing": MarketDataStatus.CONFIRMED_NAV_MISSING,
    "confirmed_fund_nav_missing_estimate_only": (
        MarketDataStatus.CONFIRMED_NAV_MISSING
    ),
}


def normalize_market_data_status(value: Any) -> MarketDataStatus:
    """Normalize legacy route/provider status text into the v0.9 vocabulary."""
    if isinstance(value, MarketDataStatus):
        return value
    if value in {None, ""}:
        return MarketDataStatus.MISSING
    key = str(value).strip().lower().replace("-", "_")
    return _STATUS_ALIASES.get(key, MarketDataStatus.MISSING)


@dataclass(frozen=True)
class MarketDataRecordMetadata:
    """Source, status, and freshness metadata shared by market data records."""

    source: str
    status: MarketDataStatus
    observed_at: datetime
    source_symbol: str | None = None
    trading_session: str | None = None
    adjustment_mode: str | None = None
    freshness: dict[str, Any] | None = None
    limitations: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["status_label_zh"] = self.status.label_zh
        payload["observed_at"] = self.observed_at.isoformat()
        payload["limitations"] = list(self.limitations)
        return {
            key: value
            for key, value in payload.items()
            if value is not None and value != ""
        }


@dataclass(frozen=True)
class MarketDataRecord:
    """One normalized market data observation with auditable status metadata."""

    kind: MarketDataEventKind
    symbol: Symbol
    asset_class: AssetClass
    timestamp: datetime
    values: dict[str, Any]
    metadata: MarketDataRecordMetadata
    frequency: BarFrequency | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind.value,
            "symbol": str(self.symbol),
            "asset_class": self.asset_class.value,
            "timestamp": self.timestamp.isoformat(),
            "values": dict(self.values),
        }
        if self.frequency is not None:
            payload["frequency"] = self.frequency.value
        payload.update(self.metadata.to_payload())
        return payload


@dataclass(frozen=True)
class MarketDataDiagnostic:
    """One localized, auditable market-data quality finding."""

    kind: MarketDataDiagnosticKind
    severity: MarketDataDiagnosticSeverity
    symbol: Symbol
    message_zh: str
    details: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "severity": self.severity.value,
            "severity_label_zh": self.severity.label_zh,
            "symbol": str(self.symbol),
            "message_zh": self.message_zh,
            "details": _jsonable(self.details),
        }


@dataclass(frozen=True)
class MarketDataQualityReport:
    """Aggregate quality result for records used by valuation or research."""

    status: MarketDataQualityStatus
    checked_at: datetime
    diagnostics: tuple[MarketDataDiagnostic, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "status_label_zh": self.status.label_zh,
            "checked_at": self.checked_at.isoformat(),
            "diagnostics": [diagnostic.to_payload() for diagnostic in self.diagnostics],
        }


def build_market_data_quality_report(
    records: Sequence[MarketDataRecord],
    *,
    expected_trading_sessions: Sequence[str] = (),
    non_trading_sessions: Sequence[str] = (),
    stale_after_seconds: int | None = None,
    provider_difference_tolerance: Decimal | int | float | str | None = None,
    symbols: Sequence[Symbol] | None = None,
    checked_at: datetime | None = None,
) -> MarketDataQualityReport:
    """Build deterministic diagnostics for market data reliability gaps."""
    checked_at = checked_at or datetime.now().astimezone()
    diagnostics: list[MarketDataDiagnostic] = []
    requested_symbols = _requested_symbols(records, symbols)
    observed_by_symbol = _observed_sessions_by_symbol(records)
    non_trading_session_set = set(non_trading_sessions)

    for symbol in requested_symbols:
        observed_sessions = observed_by_symbol.get(str(symbol), set())
        for session in expected_trading_sessions:
            if session not in observed_sessions:
                diagnostics.append(
                    MarketDataDiagnostic(
                        kind=MarketDataDiagnosticKind.MISSING_TRADING_DATE,
                        severity=MarketDataDiagnosticSeverity.BLOCKING,
                        symbol=symbol,
                        message_zh=f"{symbol} 缺少 {session} 的交易日行情。",
                        details={"trading_session": session},
                    )
                )

    for record in records:
        session = _record_session(record)
        if session in non_trading_session_set:
            diagnostics.append(
                MarketDataDiagnostic(
                    kind=MarketDataDiagnosticKind.NON_TRADING_DAY_OBSERVATION,
                    severity=MarketDataDiagnosticSeverity.WARNING,
                    symbol=record.symbol,
                    message_zh=f"{record.symbol} 在非交易日 {session} 存在行情记录。",
                    details={
                        "trading_session": session,
                        "source": record.metadata.source,
                    },
                )
            )
        if _is_stale(record, stale_after_seconds):
            diagnostics.append(
                MarketDataDiagnostic(
                    kind=MarketDataDiagnosticKind.STALE_QUOTE,
                    severity=MarketDataDiagnosticSeverity.WARNING,
                    symbol=record.symbol,
                    message_zh=f"{record.symbol} 行情已过期或超过新鲜度阈值。",
                    details={
                        "trading_session": session,
                        "source": record.metadata.source,
                        "status": record.metadata.status.value,
                        "freshness": record.metadata.freshness or {},
                    },
                )
            )
        if (
            record.asset_class is AssetClass.FUND
            and record.metadata.status is MarketDataStatus.CONFIRMED_NAV_MISSING
        ):
            diagnostics.append(
                MarketDataDiagnostic(
                    kind=MarketDataDiagnosticKind.DELAYED_FUND_NAV,
                    severity=MarketDataDiagnosticSeverity.BLOCKING,
                    symbol=record.symbol,
                    message_zh=f"{record.symbol} 确认净值缺失，当前收益只能作为估算线索。",
                    details={
                        "trading_session": session,
                        "source": record.metadata.source,
                    },
                )
            )

    diagnostics.extend(_build_adjustment_gap_diagnostics(records))
    diagnostics.extend(
        _build_provider_difference_diagnostics(
            records,
            tolerance=provider_difference_tolerance,
        )
    )

    return MarketDataQualityReport(
        status=_quality_status(diagnostics),
        checked_at=checked_at,
        diagnostics=tuple(diagnostics),
    )


class MarketDataAdapter(Protocol):
    """Capability-based adapter boundary for market data providers."""

    def fetch_daily_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> list[MarketDataRecord]:
        """Fetch normalized daily bar records."""

    def fetch_intraday_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency = BarFrequency.MIN_1,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> list[MarketDataRecord]:
        """Fetch normalized intraday bar records."""

    def fetch_snapshot(
        self,
        symbol: Symbol,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> list[MarketDataRecord]:
        """Fetch normalized latest snapshot records."""

    def fetch_ticks(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> list[MarketDataRecord]:
        """Fetch normalized tick records."""

    def replay(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> list[MarketDataRecord]:
        """Replay normalized records from a frozen local dataset."""


def _requested_symbols(
    records: Sequence[MarketDataRecord],
    symbols: Sequence[Symbol] | None,
) -> tuple[Symbol, ...]:
    if symbols is not None:
        return tuple(sorted(symbols, key=str))
    return tuple(sorted({record.symbol for record in records}, key=str))


def _observed_sessions_by_symbol(
    records: Sequence[MarketDataRecord],
) -> dict[str, set[str]]:
    observed: dict[str, set[str]] = {}
    for record in records:
        observed.setdefault(str(record.symbol), set()).add(_record_session(record))
    return observed


def _record_session(record: MarketDataRecord) -> str:
    return record.metadata.trading_session or record.timestamp.date().isoformat()


def _is_stale(
    record: MarketDataRecord,
    stale_after_seconds: int | None,
) -> bool:
    if record.metadata.status is MarketDataStatus.STALE:
        return True
    if stale_after_seconds is None:
        return False
    age_seconds = (record.metadata.freshness or {}).get("age_seconds")
    if age_seconds is None:
        return False
    try:
        return Decimal(str(age_seconds)) > Decimal(stale_after_seconds)
    except InvalidOperation:
        return False


def _build_adjustment_gap_diagnostics(
    records: Sequence[MarketDataRecord],
) -> list[MarketDataDiagnostic]:
    diagnostics: list[MarketDataDiagnostic] = []
    grouped: dict[tuple[str, str, str], list[MarketDataRecord]] = {}
    for record in records:
        grouped.setdefault(
            (str(record.symbol), _record_session(record), record.kind.value), []
        ).append(record)

    for (symbol, session, _kind), group in grouped.items():
        modes = {record.metadata.adjustment_mode or "unspecified" for record in group}
        if len(modes) <= 1:
            continue
        diagnostics.append(
            MarketDataDiagnostic(
                kind=MarketDataDiagnosticKind.ADJUSTMENT_GAP,
                severity=MarketDataDiagnosticSeverity.WARNING,
                symbol=Symbol(symbol),
                message_zh=f"{symbol} 在 {session} 存在混用复权口径的行情记录。",
                details={
                    "trading_session": session,
                    "adjustment_modes": sorted(modes),
                    "sources": sorted({record.metadata.source for record in group}),
                },
            )
        )
    return diagnostics


def _build_provider_difference_diagnostics(
    records: Sequence[MarketDataRecord],
    *,
    tolerance: Decimal | int | float | str | None,
) -> list[MarketDataDiagnostic]:
    if tolerance is None:
        return []
    tolerance_decimal = Decimal(str(tolerance))
    diagnostics: list[MarketDataDiagnostic] = []
    grouped: dict[tuple[str, str, str], list[MarketDataRecord]] = {}
    for record in records:
        grouped.setdefault(
            (str(record.symbol), _record_session(record), record.kind.value), []
        ).append(record)

    for (symbol, session, _kind), group in grouped.items():
        if len({record.metadata.source for record in group}) < 2:
            continue
        for field in ("close", "price", "nav", "last", "value"):
            values = [
                (record.metadata.source, _decimal_or_none(record.values.get(field)))
                for record in group
            ]
            values = [(source, value) for source, value in values if value is not None]
            if len(values) < 2:
                continue
            numeric_values = [value for _source, value in values]
            difference = max(numeric_values) - min(numeric_values)
            if difference <= tolerance_decimal:
                continue
            diagnostics.append(
                MarketDataDiagnostic(
                    kind=MarketDataDiagnosticKind.PROVIDER_DIFFERENCE,
                    severity=MarketDataDiagnosticSeverity.WARNING,
                    symbol=Symbol(symbol),
                    message_zh=f"{symbol} 在 {session} 的不同数据源 {field} 差异超过阈值。",
                    details={
                        "trading_session": session,
                        "field": field,
                        "difference": difference,
                        "tolerance": tolerance_decimal,
                        "sources": {source: value for source, value in values},
                    },
                )
            )
            break
    return diagnostics


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _quality_status(
    diagnostics: Sequence[MarketDataDiagnostic],
) -> MarketDataQualityStatus:
    if any(
        diagnostic.severity is MarketDataDiagnosticSeverity.BLOCKING
        for diagnostic in diagnostics
    ):
        return MarketDataQualityStatus.BLOCKED
    if diagnostics:
        return MarketDataQualityStatus.DEGRADED
    return MarketDataQualityStatus.PASS


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
