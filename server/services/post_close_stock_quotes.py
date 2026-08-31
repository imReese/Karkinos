"""Publish verified post-close stock bars through the quote-ingestion UOW."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from core.types import AssetClass, Symbol
from server.contracts.quote_ingestion import (
    QuoteIngestionCommand,
    quote_timestamp_instant,
)
from server.services.market_calendar_dates import (
    resolve_latest_verified_closed_trading_date,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_POLICY = "karkinos.post_close_stock_quote.v2"
_RECEIPT_SCHEMA = "karkinos.market_daily_ingestion_receipt.v1"
_TRIGGER = "post_close_market_bar"
_CANONICAL_SOURCE = "market_bar_close"
_TRUSTED_EQUIVALENT_SOURCES = frozenset(
    {
        "akshare",
        "akshare_stock_spot",
        "tushare_daily",
        "tushare_realtime_quote",
    }
)
_TRUSTED_SOURCE_PROVIDERS = {
    "akshare": frozenset({"akshare"}),
    "akshare_stock_spot": frozenset({"akshare"}),
    "tushare_daily": frozenset({"tushare"}),
    "tushare_realtime_quote": frozenset({"tushare"}),
}
_TRUSTED_CURRENT_STATUSES = frozenset({"confirmed", "live"})
logger = logging.getLogger(__name__)


class PostCloseStockQuoteDatabase(Protocol):
    def get_market_calendar_snapshot_sync(
        self,
        *,
        exchange: str,
        year: int,
    ) -> dict[str, Any] | None: ...

    def get_quote_fetch_run(self, run_id: str) -> dict[str, Any] | None: ...

    def get_latest_market_bar_before_date_sync(
        self,
        symbol: str,
        trade_date: str,
        frequency: str = "1d",
    ) -> dict[str, Any] | None: ...

    def get_latest_quotes_sync(self) -> list[dict[str, Any]]: ...

    def create_quote_fetch_run(self, **kwargs: Any) -> int: ...

    def persist_quote_ingestion_sync(
        self,
        command: QuoteIngestionCommand,
    ) -> dict[str, Any]: ...

    def finish_quote_fetch_run(self, **kwargs: Any) -> dict[str, Any] | None: ...


class VerifiedMarketDailyStore(Protocol):
    def get_market_daily_ingestion_receipt(
        self,
        *,
        trade_date: str,
        provider_name: str,
        verify: bool = True,
    ) -> dict[str, object] | None: ...

    def load_market_bar_windows(
        self,
        *,
        symbols: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class PostCloseStockQuoteResult:
    published: bool
    run_id: str | None
    symbols: tuple[str, ...]
    missing_symbols: tuple[str, ...] = ()
    error_message: str | None = None
    replayed: bool = False
    receipt_fingerprint: str | None = None


def publish_post_close_stock_quotes(
    database: PostCloseStockQuoteDatabase,
    data_store: VerifiedMarketDailyStore,
    watchlist: list[tuple[Symbol, AssetClass]],
    *,
    provider_name: str,
    trade_date: date,
    calendar_evidence_refs: tuple[str, ...],
    captured_at: datetime,
) -> PostCloseStockQuoteResult:
    """Atomically promote one receipt-bound stock close into current facts."""

    symbols = tuple(
        sorted(
            {
                str(symbol)
                for symbol, asset_class in watchlist
                if asset_class is AssetClass.STOCK
            }
        )
    )
    if not symbols:
        return PostCloseStockQuoteResult(True, None, ())

    trade_date_text = trade_date.isoformat()
    normalized_provider = str(provider_name).strip()
    if not normalized_provider:
        return _failed(symbols, "market_daily_provider_missing")
    resolved = resolve_latest_verified_closed_trading_date(database, captured_at)
    if (
        resolved is None
        or resolved.trade_date != trade_date_text
        or resolved.calendar_evidence_refs != calendar_evidence_refs
    ):
        return _failed(symbols, "verified_closed_trading_date_mismatch")
    try:
        receipt = data_store.get_market_daily_ingestion_receipt(
            trade_date=trade_date_text,
            provider_name=normalized_provider,
            verify=True,
        )
    except Exception as exc:
        logger.warning(
            "Verified market-daily receipt rejected: date=%s provider=%s error=%s",
            trade_date_text,
            normalized_provider,
            type(exc).__name__,
        )
        return _failed(symbols, "market_daily_ingestion_receipt_invalid")
    if not _is_valid_receipt(
        receipt,
        trade_date=trade_date_text,
        provider_name=normalized_provider,
    ):
        return _failed(symbols, "market_daily_ingestion_receipt_missing")

    receipt_symbols = {str(value) for value in receipt.get("symbols", [])}
    missing_from_receipt = tuple(
        symbol for symbol in symbols if symbol not in receipt_symbols
    )
    if missing_from_receipt:
        return _failed(
            symbols,
            "market_daily_ingestion_receipt_scope_incomplete",
            missing_symbols=missing_from_receipt,
        )

    try:
        windows = data_store.load_market_bar_windows(
            symbols=list(symbols),
            start_date=trade_date_text,
            end_date=trade_date_text,
        )
    except Exception as exc:
        logger.warning(
            "Verified market-daily bars could not be loaded: date=%s error=%s",
            trade_date_text,
            type(exc).__name__,
        )
        return _failed(symbols, "verified_market_daily_bars_unavailable")
    bars, missing_bars = _exact_bars_from_windows(
        windows,
        symbols=symbols,
        trade_date=trade_date_text,
    )
    if missing_bars:
        return _failed(
            symbols,
            "exact_target_date_market_bar_missing",
            missing_symbols=missing_bars,
        )
    try:
        receipt_after_read = data_store.get_market_daily_ingestion_receipt(
            trade_date=trade_date_text,
            provider_name=normalized_provider,
            verify=True,
        )
    except Exception:
        return _failed(symbols, "market_daily_ingestion_receipt_changed_during_read")
    if receipt_after_read != receipt:
        return _failed(symbols, "market_daily_ingestion_receipt_changed_during_read")
    resolved_after_read = resolve_latest_verified_closed_trading_date(
        database,
        captured_at,
    )
    if (
        resolved_after_read is None
        or resolved_after_read.trade_date != trade_date_text
        or resolved_after_read.calendar_evidence_refs != calendar_evidence_refs
    ):
        return _failed(symbols, "verified_market_calendar_changed_during_read")

    captured_at_value = _as_shanghai(captured_at)
    quote_timestamp = datetime.combine(
        trade_date,
        time(15, 0),
        tzinfo=_SHANGHAI_TZ,
    ).isoformat()
    current_quotes = _current_stock_quotes(database.get_latest_quotes_sync())
    promote_symbols: list[str] = []
    for symbol in symbols:
        state = _current_quote_state(
            current_quotes.get(symbol),
            bar=bars[symbol],
            trade_date=trade_date_text,
            quote_timestamp=quote_timestamp,
            provider_name=normalized_provider,
        )
        if state == "promote":
            promote_symbols.append(symbol)
        elif state == "canonical" and not _is_verified_canonical_replay(
            database,
            current_quotes.get(symbol),
            receipt=receipt,
            trade_date=trade_date_text,
            provider_name=normalized_provider,
            calendar_evidence_refs=calendar_evidence_refs,
        ):
            return _failed(symbols, "current_quote_receipt_identity_invalid")
        elif state == "conflict":
            return _failed(symbols, "current_quote_conflicts_with_verified_close")

    if not promote_symbols:
        return PostCloseStockQuoteResult(
            published=True,
            run_id=None,
            symbols=symbols,
            replayed=True,
            receipt_fingerprint=str(receipt["receipt_fingerprint"]),
        )

    input_fingerprint = _input_fingerprint(
        trade_date=trade_date_text,
        provider_name=normalized_provider,
        receipt=receipt,
        calendar_evidence_refs=calendar_evidence_refs,
        symbols=symbols,
        bars=bars,
    )
    run_id = f"{_TRIGGER}:{trade_date_text}:{uuid.uuid4().hex}"
    metadata = {
        "policy": _POLICY,
        "target_trade_date": trade_date_text,
        "symbols": list(symbols),
        "promoted_symbols": list(promote_symbols),
        "input_fingerprint": input_fingerprint,
        "receipt_fingerprint": receipt["receipt_fingerprint"],
        "market_dataset_fingerprint": receipt["dataset_fingerprint"],
        "market_data_provider": normalized_provider,
        "calendar_evidence_refs": list(calendar_evidence_refs),
        "quote_source": _CANONICAL_SOURCE,
        "provider_contact_performed": False,
        "persisted_verified_market_bars_only": True,
    }
    run_created = False
    staged_count = 0
    try:
        database.create_quote_fetch_run(
            run_id=run_id,
            started_at=captured_at_value.isoformat(),
            trigger=_TRIGGER,
            provider=normalized_provider,
            asset_type="stock",
            symbol_count=len(promote_symbols),
            status="running",
            metadata=metadata,
        )
        run_created = True
        for symbol in promote_symbols:
            database.persist_quote_ingestion_sync(
                _quote_command(
                    database,
                    run_id=run_id,
                    symbol=symbol,
                    bar=bars[symbol],
                    trade_date=trade_date_text,
                    quote_timestamp=quote_timestamp,
                    captured_at=captured_at_value.isoformat(),
                    provider_name=normalized_provider,
                    receipt=receipt,
                    calendar_evidence_refs=calendar_evidence_refs,
                )
            )
            staged_count += 1
        finished = database.finish_quote_fetch_run(
            run_id=run_id,
            finished_at=captured_at_value.isoformat(),
            status="success",
            success_count=len(promote_symbols),
            failure_count=0,
            cache_hit_count=0,
            error_message=None,
            metadata={**metadata, "staged_count": staged_count},
        )
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        if run_created:
            try:
                database.finish_quote_fetch_run(
                    run_id=run_id,
                    finished_at=captured_at_value.isoformat(),
                    status="failed",
                    success_count=0,
                    failure_count=len(promote_symbols),
                    cache_hit_count=0,
                    error_message=error_message,
                    metadata={
                        **metadata,
                        "staged_count": staged_count,
                        "publication_error": error_message,
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to terminalize post-close quote run: %s",
                    run_id,
                )
        return _failed(
            symbols,
            error_message,
            run_id=run_id if run_created else None,
        )

    if not isinstance(finished, dict) or str(finished.get("status") or "") != (
        "success"
    ):
        return _failed(
            symbols,
            str(
                (finished or {}).get("error_message")
                or "post_close_quote_batch_not_published"
            ),
            run_id=run_id,
        )
    verification_error = _verify_published_facts(
        database.get_latest_quotes_sync(),
        database=database,
        symbols=symbols,
        promoted_symbols=frozenset(promote_symbols),
        bars=bars,
        trade_date=trade_date_text,
        quote_timestamp=quote_timestamp,
        provider_name=normalized_provider,
        receipt=receipt,
        run_id=run_id,
        calendar_evidence_refs=calendar_evidence_refs,
    )
    if verification_error is not None:
        return _failed(symbols, verification_error, run_id=run_id)
    return PostCloseStockQuoteResult(
        True,
        run_id,
        symbols,
        receipt_fingerprint=str(receipt["receipt_fingerprint"]),
    )


def _quote_command(
    database: PostCloseStockQuoteDatabase,
    *,
    run_id: str,
    symbol: str,
    bar: dict[str, Any],
    trade_date: str,
    quote_timestamp: str,
    captured_at: str,
    provider_name: str,
    receipt: dict[str, object],
    calendar_evidence_refs: tuple[str, ...],
) -> QuoteIngestionCommand:
    close_price = float(bar["close"])
    previous = database.get_latest_market_bar_before_date_sync(symbol, trade_date)
    previous_close = _positive_float(
        (previous or {}).get("close", (previous or {}).get("price"))
    )
    previous_close_date = (
        _bar_trade_date(previous) if previous_close is not None else None
    )
    change = close_price - previous_close if previous_close is not None else None
    change_percent = (
        change / previous_close * 100.0 if previous_close is not None else None
    )
    return QuoteIngestionCommand(
        symbol=symbol,
        asset_type="stock",
        price=close_price,
        volume=_non_negative_float(bar.get("volume")),
        previous_close=previous_close,
        previous_close_date=previous_close_date,
        change=change,
        change_percent=change_percent,
        turnover=_non_negative_float(bar.get("amount")),
        quote_timestamp=quote_timestamp,
        quote_source=_CANONICAL_SOURCE,
        provider_name=provider_name,
        provider_status="persisted_verified",
        quote_status="confirmed",
        captured_at=captured_at,
        captured_reason="post_close_market_bar",
        fetch_run_id=run_id,
        provider_symbol=symbol,
        source="market_bars",
        metadata={
            "policy": _POLICY,
            "market_bar_timestamp": str(bar.get("timestamp") or ""),
            "receipt_fingerprint": receipt["receipt_fingerprint"],
            "market_dataset_fingerprint": receipt["dataset_fingerprint"],
            "calendar_evidence_refs": list(calendar_evidence_refs),
        },
        daily_close_price=close_price,
        daily_close_date=trade_date,
        daily_close_source=_CANONICAL_SOURCE,
    )


def _verify_published_facts(
    rows: list[dict[str, Any]],
    *,
    database: PostCloseStockQuoteDatabase,
    symbols: tuple[str, ...],
    promoted_symbols: frozenset[str],
    bars: dict[str, dict[str, Any]],
    trade_date: str,
    quote_timestamp: str,
    provider_name: str,
    receipt: dict[str, object],
    run_id: str,
    calendar_evidence_refs: tuple[str, ...],
) -> str | None:
    current = _current_stock_quotes(rows)
    target_instant = quote_timestamp_instant(quote_timestamp)
    for symbol in symbols:
        row = current.get(symbol)
        state = _current_quote_state(
            row,
            bar=bars[symbol],
            trade_date=trade_date,
            quote_timestamp=quote_timestamp,
            provider_name=provider_name,
        )
        if state in {"promote", "conflict"}:
            return "post_close_quote_publication_verification_failed"
        if state == "canonical" and not _is_verified_canonical_replay(
            database,
            row,
            receipt=receipt,
            trade_date=trade_date,
            provider_name=provider_name,
            calendar_evidence_refs=calendar_evidence_refs,
        ):
            return "post_close_quote_publication_receipt_identity_invalid"
        if symbol not in promoted_symbols or row is None:
            continue
        current_instant = quote_timestamp_instant(_quote_timestamp(row))
        if current_instant == target_instant and (
            str(row.get("quote_source") or "") != _CANONICAL_SOURCE
            or str(row.get("provider_name") or "") != provider_name
            or str(row.get("quote_status") or "") != "confirmed"
            or str(row.get("provider_status") or "") != "persisted_verified"
            or str(row.get("fetch_run_id") or "") != run_id
            or not _prices_equal(row.get("price"), bars[symbol].get("close"))
        ):
            return "post_close_quote_publication_identity_mismatch"
    return None


def _current_quote_state(
    row: dict[str, Any] | None,
    *,
    bar: dict[str, Any],
    trade_date: str,
    quote_timestamp: str,
    provider_name: str,
) -> str:
    if not row:
        return "promote"
    current_instant = quote_timestamp_instant(_quote_timestamp(row))
    target_instant = quote_timestamp_instant(quote_timestamp)
    if current_instant < target_instant:
        return "promote"
    source = str(row.get("quote_source") or row.get("source") or "").strip()
    persisted_provider = str(row.get("provider_name") or "").strip().lower()
    status = str(row.get("quote_status") or "").strip().lower()
    provider_status = str(row.get("provider_status") or "").strip().lower()
    trusted = (
        source == _CANONICAL_SOURCE
        and persisted_provider == provider_name.lower()
        and status == "confirmed"
        and provider_status == "persisted_verified"
        and bool(str(row.get("fetch_run_id") or "").strip())
    ) or (
        source in _TRUSTED_EQUIVALENT_SOURCES
        and persisted_provider in _TRUSTED_SOURCE_PROVIDERS[source]
        and status in _TRUSTED_CURRENT_STATUSES
        and provider_status == "live"
    )
    if not trusted or row.get("stale_reason") not in {None, ""}:
        return "conflict"
    if current_instant == target_instant:
        if not _prices_equal(row.get("price"), bar.get("close")):
            return "conflict"
        if source == _CANONICAL_SOURCE:
            return (
                "canonical"
                if str(row.get("provider_status") or "") == "persisted_verified"
                and str(row.get("fetch_run_id") or "").strip()
                else "conflict"
            )
        return "equivalent"
    current_date = _quote_local_date(row)
    if current_date is None or current_date < trade_date:
        return "conflict"
    if current_date == trade_date and not _prices_equal(
        row.get("price"), bar.get("close")
    ):
        return "conflict"
    return "newer"


def _is_verified_canonical_replay(
    database: PostCloseStockQuoteDatabase,
    row: dict[str, Any] | None,
    *,
    receipt: dict[str, object],
    trade_date: str,
    provider_name: str,
    calendar_evidence_refs: tuple[str, ...],
) -> bool:
    if row is None:
        return False
    run_id = str(row.get("fetch_run_id") or "").strip()
    if not run_id:
        return False
    try:
        run = database.get_quote_fetch_run(run_id)
    except Exception:
        return False
    if not isinstance(run, dict) or str(run.get("status") or "") != "success":
        return False
    metadata = _run_metadata(run)
    return bool(
        str(run.get("trigger") or "") == _TRIGGER
        and str(run.get("provider") or "") == provider_name
        and metadata.get("policy") == _POLICY
        and metadata.get("target_trade_date") == trade_date
        and metadata.get("market_data_provider") == provider_name
        and metadata.get("receipt_fingerprint") == receipt.get("receipt_fingerprint")
        and metadata.get("market_dataset_fingerprint")
        == receipt.get("dataset_fingerprint")
        and metadata.get("calendar_evidence_refs") == list(calendar_evidence_refs)
    )


def _run_metadata(run: dict[str, Any]) -> dict[str, Any]:
    value = run.get("metadata")
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(run.get("metadata_json") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _current_stock_quotes(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("symbol") or ""): row
        for row in rows
        if str(row.get("asset_type") or row.get("asset_class") or "") == "stock"
    }


def _exact_bars_from_windows(
    windows: dict[str, Any],
    *,
    symbols: tuple[str, ...],
    trade_date: str,
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    bars: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for symbol in symbols:
        frame = windows.get(symbol)
        if frame is None or getattr(frame, "empty", True) or len(frame.index) != 1:
            missing.append(symbol)
            continue
        row = dict(frame.iloc[0].to_dict())
        row["symbol"] = symbol
        row["frequency"] = "1d"
        row["timestamp"] = str(row.get("timestamp") or "")
        if not _is_exact_valid_bar(row, symbol=symbol, trade_date=trade_date):
            missing.append(symbol)
            continue
        bars[symbol] = row
    return bars, tuple(missing)


def _is_valid_receipt(
    receipt: dict[str, object] | None,
    *,
    trade_date: str,
    provider_name: str,
) -> bool:
    if not isinstance(receipt, dict):
        return False
    return bool(
        receipt.get("schema_version") == _RECEIPT_SCHEMA
        and receipt.get("trade_date") == trade_date
        and receipt.get("provider_name") == provider_name
        and receipt.get("storage_authority") == "sqlite_market_bars"
        and isinstance(receipt.get("symbols"), list)
        and receipt.get("symbols")
        and receipt.get("row_count") == len(set(receipt.get("symbols", [])))
        and str(receipt.get("receipt_fingerprint") or "").startswith("sha256:")
        and str(receipt.get("dataset_fingerprint") or "")
    )


def _is_exact_valid_bar(
    bar: dict[str, Any] | None,
    *,
    symbol: str,
    trade_date: str,
) -> bool:
    if not isinstance(bar, dict) or _bar_trade_date(bar) != trade_date:
        return False
    if bar.get("symbol") not in {None, "", symbol}:
        return False
    if bar.get("frequency") not in {None, "", "1d"}:
        return False
    if _positive_float(bar.get("close", bar.get("price"))) is None:
        return False
    return all(
        value in {None, ""} or _non_negative_float(value) is not None
        for value in (bar.get("volume"), bar.get("amount"))
    )


def _quote_timestamp(row: dict[str, Any]) -> object:
    return row.get("quote_timestamp") or row.get("timestamp")


def _quote_local_date(row: dict[str, Any]) -> str | None:
    value = str(_quote_timestamp(row) or "").strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed.astimezone(_SHANGHAI_TZ).date().isoformat()


def _bar_trade_date(bar: dict[str, Any] | None) -> str | None:
    if not isinstance(bar, dict):
        return None
    value = str(bar.get("trade_date") or bar.get("timestamp") or "").strip()
    return value[:10] if len(value) >= 10 else None


def _prices_equal(left: object, right: object) -> bool:
    left_value = _positive_float(left)
    right_value = _positive_float(right)
    return bool(
        left_value is not None
        and right_value is not None
        and math.isclose(left_value, right_value, rel_tol=1e-12, abs_tol=1e-9)
    )


def _positive_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _non_negative_float(value: object) -> float | None:
    if value in {None, ""}:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _input_fingerprint(
    *,
    trade_date: str,
    provider_name: str,
    receipt: dict[str, object],
    calendar_evidence_refs: tuple[str, ...],
    symbols: tuple[str, ...],
    bars: dict[str, dict[str, Any]],
) -> str:
    payload = {
        "policy": _POLICY,
        "trade_date": trade_date,
        "provider_name": provider_name,
        "receipt_fingerprint": receipt["receipt_fingerprint"],
        "calendar_evidence_refs": list(calendar_evidence_refs),
        "bars": [
            {
                "symbol": symbol,
                "timestamp": str(bars[symbol].get("timestamp") or ""),
                "close": float(bars[symbol]["close"]),
                "volume": _non_negative_float(bars[symbol].get("volume")),
                "amount": _non_negative_float(bars[symbol].get("amount")),
            }
            for symbol in symbols
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _failed(
    symbols: tuple[str, ...],
    error_message: str,
    *,
    missing_symbols: tuple[str, ...] = (),
    run_id: str | None = None,
) -> PostCloseStockQuoteResult:
    return PostCloseStockQuoteResult(
        published=False,
        run_id=run_id,
        symbols=symbols,
        missing_symbols=missing_symbols,
        error_message=error_message,
    )


def _as_shanghai(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=_SHANGHAI_TZ)
    return value.astimezone(_SHANGHAI_TZ)


__all__ = [
    "PostCloseStockQuoteResult",
    "publish_post_close_stock_quotes",
]
