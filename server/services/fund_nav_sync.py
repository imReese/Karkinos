"""Fund NAV quote synchronization for scheduler-owned watchlists."""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from core.types import AssetClass, InstrumentType, Symbol
from data.manager import build_sources
from server.services.market_hours import get_shanghai_now
from server.services.market_quote_ingestion import (
    build_quote_ingestion_command,
    persist_quote_ingestion,
)

logger = logging.getLogger(__name__)

FUND_NAV_SYNC_TTL_SECONDS = 15 * 60
_CONFIRMED_FUND_NAV_SOURCES = {
    "eastmoney_fund_page",
    "tushare_fund_nav",
}


@dataclass(slots=True)
class FundNavSyncResult:
    refreshed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    quotes: dict[str, dict[str, Any]] = field(default_factory=dict)
    run_id: str | None = None
    request_id: str | None = None
    idempotent_replay: bool = False


class FundNavSyncIdempotencyConflict(ValueError):
    """Raised when one request id is reused with a different ingestion scope."""


def _request_run_id(request_id: str | None) -> tuple[str | None, str | None]:
    value = str(request_id or "").strip()
    if not value:
        return None, None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", value):
        raise ValueError("invalid fund NAV ingestion request id")
    return value, f"fund_nav_sync:request:{value}"


def _run_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    raw = row.get("metadata_json")
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _replay_fund_nav_result(
    row: dict[str, Any],
    *,
    request_id: str,
    expected_symbols: list[str],
    confirmation_only: bool,
    expected_target_date: str | None,
    manual_explicit_trigger: bool,
) -> FundNavSyncResult:
    metadata = _run_metadata(row)
    persisted_symbols = _string_list(
        metadata.get("request_scope_symbols") or metadata.get("requested_symbols")
    )
    if (
        persisted_symbols != expected_symbols
        or bool(metadata.get("confirmation_only")) is not confirmation_only
        or str(metadata.get("target_date") or "") != str(expected_target_date or "")
        or bool(metadata.get("manual_explicit_trigger")) is not manual_explicit_trigger
    ):
        raise FundNavSyncIdempotencyConflict(
            "fund NAV ingestion request id was reused with a different payload"
        )

    failed_details = metadata.get("failed_details")
    failed = (
        {str(key): str(value) for key, value in failed_details.items()}
        if isinstance(failed_details, dict)
        else {
            symbol: str(row.get("error_message") or "previous ingestion failed")
            for symbol in _string_list(metadata.get("failed_symbols"))
        }
    )
    refreshed = _string_list(metadata.get("refreshed_symbols"))
    publication_ready = bool(
        str(row.get("status") or "") in {"success", "partial", "partial_success"}
        and str(metadata.get("valuation_snapshot_id") or "").strip()
    )
    if refreshed and not publication_ready:
        refreshed = []
        failed.setdefault("__publication__", "quote_batch_publication_failed")
    return FundNavSyncResult(
        refreshed=refreshed,
        skipped=_string_list(metadata.get("skipped_symbols")),
        failed=failed,
        run_id=str(row["run_id"]),
        request_id=request_id,
        idempotent_replay=True,
    )


def _open_end_fund_symbols(
    watchlist: list[tuple[Symbol, InstrumentType | AssetClass | str]],
) -> list[str]:
    """Select only explicit open-end funds; broad FUND is not authoritative."""

    symbols: list[str] = []
    for symbol, raw_identity in watchlist:
        if isinstance(raw_identity, InstrumentType):
            instrument_type = raw_identity
        elif isinstance(raw_identity, AssetClass):
            if raw_identity is AssetClass.FUND:
                raise ValueError(
                    f"canonical fund instrument type is required for {symbol}"
                )
            instrument_type = InstrumentType.from_persisted(raw_identity.value)
        else:
            instrument_type = InstrumentType.from_persisted(raw_identity)
        if instrument_type is InstrumentType.OPEN_END_FUND:
            symbols.append(str(symbol))
    return symbols


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fund_quote_due(
    quote: dict[str, Any] | None,
    *,
    now: datetime,
    ttl_seconds: int,
    confirmation_only: bool = False,
    target_date: str | None = None,
) -> bool:
    if ttl_seconds <= 0:
        return True
    if not quote:
        return True
    if confirmation_only:
        return not is_confirmed_fund_nav_quote(
            quote,
            target_date=target_date or get_shanghai_now(now).date().isoformat(),
        )
    timestamp = _parse_timestamp(
        quote.get("timestamp")
        or quote.get("quote_timestamp")
        or quote.get("captured_at")
    )
    if timestamp is None:
        return True
    if timestamp.tzinfo is not None and now.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=None)
    return (now - timestamp).total_seconds() >= ttl_seconds


def is_confirmed_fund_nav_quote(
    quote: dict[str, Any] | None,
    *,
    target_date: str,
) -> bool:
    """Return whether one persisted fund fact is a usable confirmed NAV."""

    if not isinstance(quote, dict):
        return False
    quote_source = (
        str(quote.get("quote_source") or quote.get("source") or "").strip().lower()
    )
    if quote_source not in _CONFIRMED_FUND_NAV_SOURCES:
        return False
    if str(quote.get("nav_date") or "").strip() != target_date:
        return False
    try:
        price = float(quote.get("price"))
    except (TypeError, ValueError):
        return False
    return bool(
        math.isfinite(price)
        and price > 0
        and str(quote.get("provider_status") or "").strip().lower() == "live"
        and str(quote.get("quote_status") or "").strip().lower()
        in {"confirmed", "live"}
        and quote.get("stale_reason") in {None, ""}
    )


def _source_chain(
    config: Any,
    *,
    confirmation_only: bool = False,
) -> list[tuple[str, Any]]:
    data_source = str(getattr(config, "data_source", "akshare") or "akshare")
    sources = build_sources(
        data_source=data_source,
        tushare_token=str(getattr(config, "tushare_token", "") or ""),
    )
    ordered: list[tuple[str, Any]] = []
    source_order = (
        (data_source, "akshare") if confirmation_only else ("akshare", data_source)
    )
    for name in source_order:
        source = sources.get(name)
        if source is not None and all(
            existing is not source for _, existing in ordered
        ):
            ordered.append((name, source))
    return ordered


def _normalize_snapshot(
    *,
    symbol: str,
    snapshot: dict[str, Any],
    source_name: str,
    now: datetime,
) -> dict[str, Any]:
    price = snapshot.get("price")
    if price is None or str(price).strip() == "":
        raise ValueError("fund snapshot missing price")
    quote_source = str(
        snapshot.get("quote_source") or snapshot.get("source") or source_name
    )
    provider_name = str(
        snapshot.get("provider_name") or snapshot.get("provider") or source_name
    )
    timestamp = str(snapshot.get("timestamp") or now.isoformat())
    nav_date = snapshot.get("nav_date")
    if not nav_date and quote_source.strip().lower() in _CONFIRMED_FUND_NAV_SOURCES:
        parsed_timestamp = _parse_timestamp(timestamp)
        nav_date = (
            parsed_timestamp.date().isoformat()
            if parsed_timestamp is not None
            else None
        )
    return {
        "symbol": symbol,
        "asset_class": AssetClass.FUND.value,
        "instrument_type": InstrumentType.OPEN_END_FUND.value,
        "price": float(price),
        "volume": (
            None
            if snapshot.get("volume") in {None, ""}
            else float(snapshot.get("volume"))
        ),
        "timestamp": timestamp,
        "quote_source": quote_source,
        "provider_name": provider_name,
        "provider_status": "live",
        "quote_status": (
            "confirmed"
            if quote_source.strip().lower() in _CONFIRMED_FUND_NAV_SOURCES
            else "live"
        ),
        "captured_reason": "fund_nav_sync",
        "nav_date": nav_date,
        "display_name": snapshot.get("display_name")
        or snapshot.get("name")
        or snapshot.get("asset_name"),
        "provider_symbol": snapshot.get("provider_symbol") or symbol,
        "source": snapshot.get("source") or quote_source,
    }


def _persist_fund_quote(
    db: Any,
    quote: dict[str, Any],
    *,
    now: datetime,
    fetch_run_id: str,
) -> None:
    command = build_quote_ingestion_command(
        symbol=str(quote["symbol"]),
        asset_type=InstrumentType.OPEN_END_FUND.value,
        snapshot=quote,
        quote_source=str(quote["quote_source"]),
        provider_name=str(quote["provider_name"]),
        provider_status=str(quote["provider_status"]),
        quote_status=str(quote["quote_status"]),
        captured_reason=str(quote["captured_reason"]),
        captured_at=now.isoformat(),
        nav_date=str(quote["nav_date"]) if quote.get("nav_date") else None,
        fetch_run_id=fetch_run_id,
    )
    persist_quote_ingestion(db, command)


def refresh_fund_nav_quotes(
    config: Any,
    db: Any,
    watchlist: list[tuple[Symbol, InstrumentType | AssetClass | str]],
    latest_quotes: dict[str, dict[str, Any]],
    *,
    now: datetime | None = None,
    ttl_seconds: int = FUND_NAV_SYNC_TTL_SECONDS,
    confirmation_only: bool = False,
    target_date: str | None = None,
    request_id: str | None = None,
    manual_explicit_trigger: bool = False,
) -> FundNavSyncResult:
    """Refresh open-end fund NAV/estimate quotes and materialize latest prices."""
    current = now or datetime.now()
    confirmation_target_date = (
        str(target_date).strip()
        if target_date is not None
        else get_shanghai_now(current).date().isoformat()
    )
    if confirmation_only:
        try:
            date.fromisoformat(confirmation_target_date)
        except ValueError as exc:
            raise ValueError("invalid confirmed fund NAV target date") from exc
    normalized_request_id, request_run_id = _request_run_id(request_id)
    result = FundNavSyncResult(request_id=normalized_request_id)
    fund_symbols = _open_end_fund_symbols(watchlist)
    if not fund_symbols:
        return result

    get_run = getattr(db, "get_quote_fetch_run", None)
    if request_run_id is not None and not callable(get_run):
        raise RuntimeError("fund NAV idempotency storage unavailable")
    if request_run_id is not None:
        existing_run = get_run(request_run_id)
        if existing_run is not None:
            return _replay_fund_nav_result(
                existing_run,
                request_id=normalized_request_id or "",
                expected_symbols=fund_symbols,
                confirmation_only=confirmation_only,
                expected_target_date=(
                    confirmation_target_date if confirmation_only else None
                ),
                manual_explicit_trigger=manual_explicit_trigger,
            )

    due_symbols = []
    for symbol in fund_symbols:
        current_quote = latest_quotes.get(symbol)
        if confirmation_only:
            persisted_reader = getattr(db, "get_latest_quote_sync", None)
            try:
                current_quote = (
                    persisted_reader(symbol, asset_type="open_end_fund")
                    if callable(persisted_reader)
                    else None
                )
            except Exception:
                current_quote = None
        if _fund_quote_due(
            current_quote,
            now=current,
            ttl_seconds=ttl_seconds,
            confirmation_only=confirmation_only,
            target_date=confirmation_target_date,
        ):
            due_symbols.append(symbol)
        else:
            result.skipped.append(symbol)
    if not due_symbols:
        return result

    run_id = request_run_id or f"fund_nav_sync:{current.isoformat()}:{uuid.uuid4().hex}"
    result.run_id = run_id
    create_run = getattr(db, "create_quote_fetch_run", None)
    finish_run = getattr(db, "finish_quote_fetch_run", None)
    if request_run_id is not None and not callable(create_run):
        raise RuntimeError("fund NAV idempotency storage unavailable")
    if callable(create_run):
        try:
            create_run(
                run_id=run_id,
                started_at=current.isoformat(),
                trigger="fund_nav_sync",
                provider=str(getattr(config, "data_source", "akshare") or "akshare"),
                asset_type=InstrumentType.OPEN_END_FUND.value,
                symbol_count=len(due_symbols),
                status="running",
                metadata={
                    "request_id": normalized_request_id,
                    "request_scope_symbols": fund_symbols,
                    "requested_symbols": due_symbols,
                    "confirmation_only": confirmation_only,
                    "target_date": (
                        confirmation_target_date if confirmation_only else None
                    ),
                    "manual_explicit_trigger": manual_explicit_trigger,
                },
            )
        except Exception:
            existing_run = get_run(run_id) if callable(get_run) else None
            if normalized_request_id and existing_run is not None:
                return _replay_fund_nav_result(
                    existing_run,
                    request_id=normalized_request_id,
                    expected_symbols=fund_symbols,
                    confirmation_only=confirmation_only,
                    expected_target_date=(
                        confirmation_target_date if confirmation_only else None
                    ),
                    manual_explicit_trigger=manual_explicit_trigger,
                )
            raise

    sources = _source_chain(config, confirmation_only=confirmation_only)
    if not sources:
        for symbol in due_symbols:
            result.failed[symbol] = "no fund quote source configured"
        if callable(finish_run):
            finish_run(
                run_id=run_id,
                finished_at=current.isoformat(),
                status="failed",
                failure_count=len(due_symbols),
                error_message="no fund quote source configured",
                metadata={
                    "request_id": normalized_request_id,
                    "request_scope_symbols": fund_symbols,
                    "requested_symbols": due_symbols,
                    "refreshed_symbols": [],
                    "skipped_symbols": result.skipped,
                    "failed_symbols": sorted(result.failed),
                    "failed_details": result.failed,
                    "confirmation_only": confirmation_only,
                    "target_date": (
                        confirmation_target_date if confirmation_only else None
                    ),
                    "manual_explicit_trigger": manual_explicit_trigger,
                },
            )
        return result

    pending_quotes: dict[str, dict[str, Any]] = {}
    for symbol in due_symbols:
        last_error: str | None = None
        for source_name, source in sources:
            try:
                fetch_confirmed = getattr(source, "fetch_confirmed_fund_nav", None)
                snapshot = (
                    fetch_confirmed(Symbol(symbol))
                    if confirmation_only and callable(fetch_confirmed)
                    else source.fetch_latest(Symbol(symbol), AssetClass.FUND)
                )
                if snapshot is None:
                    raise ValueError("fund source returned no snapshot")
                quote_source = (
                    str(snapshot.get("quote_source") or snapshot.get("source") or "")
                    .strip()
                    .lower()
                )
                if (
                    confirmation_only
                    and quote_source not in _CONFIRMED_FUND_NAV_SOURCES
                ):
                    raise ValueError("fund source returned an unconfirmed NAV estimate")
                if confirmation_only:
                    confirmed_timestamp = _parse_timestamp(
                        snapshot.get("nav_date") or snapshot.get("timestamp")
                    )
                    if (
                        confirmed_timestamp is None
                        or confirmed_timestamp.date().isoformat()
                        != confirmation_target_date
                    ):
                        raise ValueError(
                            "confirmed fund NAV is not published for the target date"
                        )
                quote = _normalize_snapshot(
                    symbol=symbol,
                    snapshot=dict(snapshot),
                    source_name=source_name,
                    now=current,
                )
                pending_quotes[symbol] = quote
                last_error = None
                break
            except Exception as exc:
                last_error = str(exc)
                logger.debug(
                    "Fund NAV refresh failed for %s via %s",
                    symbol,
                    source_name,
                    exc_info=True,
                )
        if last_error is not None:
            result.failed[symbol] = last_error

    # External provider I/O completes before any account valuation input is
    # changed. This keeps a slow or partially fetched batch from exposing a
    # long-lived, unpublished quote set to financial reads.
    staged_quotes: dict[str, dict[str, Any]] = {}
    for symbol, quote in pending_quotes.items():
        try:
            if db is not None:
                _persist_fund_quote(
                    db,
                    quote,
                    now=current,
                    fetch_run_id=run_id,
                )
            staged_quotes[symbol] = quote
            result.refreshed.append(symbol)
        except Exception as exc:
            result.failed[symbol] = str(exc)
            logger.exception("Failed to persist fund NAV quote for %s", symbol)

    publication_error: str | None = None
    finished: dict[str, Any] | None = None
    if callable(finish_run):
        success_count = len(result.refreshed)
        symbol_failure_count = sum(
            1 for symbol in due_symbols if symbol in result.failed
        )
        failure_count = symbol_failure_count
        if failure_count and not success_count:
            status = "failed"
        elif failure_count:
            status = "partial_success"
        else:
            status = "success"
        try:
            finished = finish_run(
                run_id=run_id,
                finished_at=datetime.now().isoformat(),
                status=status,
                success_count=success_count,
                failure_count=failure_count,
                error_message=None,
                metadata={
                    "request_id": normalized_request_id,
                    "request_scope_symbols": fund_symbols,
                    "requested_symbols": due_symbols,
                    "refreshed_symbols": result.refreshed,
                    "skipped_symbols": result.skipped,
                    "failed_symbols": sorted(
                        symbol
                        for symbol in result.failed
                        if not symbol.startswith("__")
                    ),
                    "failed_details": result.failed,
                    "confirmation_only": confirmation_only,
                    "target_date": (
                        confirmation_target_date if confirmation_only else None
                    ),
                    "manual_explicit_trigger": manual_explicit_trigger,
                },
            )
        except Exception:
            logger.exception("Failed to publish staged fund NAV quote batch")
    published = bool(
        isinstance(finished, dict)
        and finished.get("status") in {"success", "partial", "partial_success"}
        and "valuation_snapshot_id" in _run_metadata(finished)
    )
    if not published and staged_quotes:
        publication_error = "quote_batch_publication_failed"
        result.failed["__publication__"] = publication_error
        result.refreshed.clear()
        return result
    for symbol, quote in staged_quotes.items():
        cached_quote = {
            "price": quote["price"],
            "volume": quote["volume"],
            "timestamp": quote["timestamp"],
            "asset_class": quote["asset_class"],
            "instrument_type": quote["instrument_type"],
            "quote_source": quote["quote_source"],
            "provider_name": quote["provider_name"],
            "quote_status": quote["quote_status"],
            "provider_status": quote["provider_status"],
            "captured_reason": quote["captured_reason"],
            "nav_date": quote["nav_date"],
        }
        latest_quotes[symbol] = cached_quote
        result.quotes[symbol] = cached_quote
    return result


__all__ = [
    "FUND_NAV_SYNC_TTL_SECONDS",
    "FundNavSyncIdempotencyConflict",
    "FundNavSyncResult",
    "is_confirmed_fund_nav_quote",
    "refresh_fund_nav_quotes",
]
