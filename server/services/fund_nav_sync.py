"""Fund NAV quote synchronization for scheduler-owned watchlists."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.types import AssetClass, Symbol
from data.manager import build_sources
from server.services.valuation_snapshot import build_current_valuation_snapshot

logger = logging.getLogger(__name__)

FUND_NAV_SYNC_TTL_SECONDS = 15 * 60


@dataclass(slots=True)
class FundNavSyncResult:
    refreshed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    quotes: dict[str, dict[str, Any]] = field(default_factory=dict)
    run_id: str | None = None


def _is_fund_asset_class(asset_class: AssetClass | str) -> bool:
    if isinstance(asset_class, AssetClass):
        return asset_class is AssetClass.FUND
    return str(asset_class).strip().lower() in {"fund", "etf"}


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
) -> bool:
    if ttl_seconds <= 0:
        return True
    if not quote:
        return True
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


def _source_chain(config: Any) -> list[tuple[str, Any]]:
    data_source = str(getattr(config, "data_source", "akshare") or "akshare")
    sources = build_sources(
        data_source=data_source,
        tushare_token=str(getattr(config, "tushare_token", "") or ""),
    )
    ordered: list[tuple[str, Any]] = []
    for name in ("akshare", data_source):
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
    return {
        "symbol": symbol,
        "asset_class": AssetClass.FUND.value,
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
        "quote_status": "live",
        "captured_reason": "fund_nav_sync",
        "nav_date": snapshot.get("nav_date"),
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
    if hasattr(db, "save_quote_snapshot_sync"):
        db.save_quote_snapshot_sync(
            symbol=quote["symbol"],
            asset_class=AssetClass.FUND.value,
            price=quote["price"],
            volume=quote["volume"],
            timestamp=quote["timestamp"],
            quote_source=quote["quote_source"],
            provider_name=quote["provider_name"],
            quote_status=quote["quote_status"],
            provider_status=quote["provider_status"],
            captured_reason=quote["captured_reason"],
            nav_date=quote["nav_date"],
            fetch_run_id=fetch_run_id,
        )
    if hasattr(db, "upsert_latest_quote_sync"):
        db.upsert_latest_quote_sync(
            symbol=quote["symbol"],
            asset_type=AssetClass.FUND.value,
            price=quote["price"],
            volume=quote["volume"],
            quote_timestamp=quote["timestamp"],
            quote_source=quote["quote_source"],
            provider_name=quote["provider_name"],
            provider_status=quote["provider_status"],
            quote_status=quote["quote_status"],
            captured_at=now.isoformat(),
            captured_reason=quote["captured_reason"],
            nav_date=quote["nav_date"],
            fetch_run_id=fetch_run_id,
            metadata={
                "source": quote["source"],
                "quote_source": quote["quote_source"],
                "nav_date": quote["nav_date"],
            },
        )
    display_name = str(quote.get("display_name") or "").strip()
    if display_name and hasattr(db, "upsert_instrument_metadata_sync"):
        db.upsert_instrument_metadata_sync(
            symbol=quote["symbol"],
            asset_type=AssetClass.FUND.value,
            display_name=display_name,
            provider_symbol=str(quote.get("provider_symbol") or quote["symbol"]),
            provider_name=quote["provider_name"],
            source="fund_nav_sync",
            fetched_at=quote["timestamp"],
            metadata={
                "source": quote["source"],
                "quote_source": quote["quote_source"],
            },
        )


def refresh_fund_nav_quotes(
    config: Any,
    db: Any,
    watchlist: list[tuple[Symbol, AssetClass]],
    latest_quotes: dict[str, dict[str, Any]],
    *,
    now: datetime | None = None,
    ttl_seconds: int = FUND_NAV_SYNC_TTL_SECONDS,
) -> FundNavSyncResult:
    """Refresh open-end fund NAV/estimate quotes and materialize latest prices."""
    current = now or datetime.now()
    result = FundNavSyncResult()
    fund_symbols = [
        str(symbol)
        for symbol, asset_class in watchlist
        if _is_fund_asset_class(asset_class)
    ]
    if not fund_symbols:
        return result

    due_symbols = []
    for symbol in fund_symbols:
        if _fund_quote_due(
            latest_quotes.get(symbol),
            now=current,
            ttl_seconds=ttl_seconds,
        ):
            due_symbols.append(symbol)
        else:
            result.skipped.append(symbol)
    if not due_symbols:
        return result

    run_id = f"fund_nav_sync:{current.isoformat()}:{uuid.uuid4().hex}"
    result.run_id = run_id
    create_run = getattr(db, "create_quote_fetch_run", None)
    finish_run = getattr(db, "finish_quote_fetch_run", None)
    if callable(create_run):
        create_run(
            run_id=run_id,
            started_at=current.isoformat(),
            trigger="fund_nav_sync",
            provider=str(getattr(config, "data_source", "akshare") or "akshare"),
            asset_type=AssetClass.FUND.value,
            symbol_count=len(due_symbols),
            status="running",
            metadata={"requested_symbols": due_symbols},
        )

    sources = _source_chain(config)
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
                metadata={"requested_symbols": due_symbols},
            )
        return result

    for symbol in due_symbols:
        last_error: str | None = None
        for source_name, source in sources:
            try:
                snapshot = source.fetch_latest(Symbol(symbol), AssetClass.FUND)
                quote = _normalize_snapshot(
                    symbol=symbol,
                    snapshot=dict(snapshot),
                    source_name=source_name,
                    now=current,
                )
                if db is not None:
                    _persist_fund_quote(
                        db,
                        quote,
                        now=current,
                        fetch_run_id=run_id,
                    )
                cached_quote = {
                    "price": quote["price"],
                    "volume": quote["volume"],
                    "timestamp": quote["timestamp"],
                    "asset_class": quote["asset_class"],
                    "quote_source": quote["quote_source"],
                    "provider_name": quote["provider_name"],
                    "quote_status": quote["quote_status"],
                    "provider_status": quote["provider_status"],
                    "captured_reason": quote["captured_reason"],
                    "nav_date": quote["nav_date"],
                }
                latest_quotes[symbol] = cached_quote
                result.quotes[symbol] = cached_quote
                result.refreshed.append(symbol)
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

    valuation_snapshot_id: str | None = None
    publication_error: str | None = None
    try:
        valuation_snapshot = build_current_valuation_snapshot(db, persist=True)
        valuation_snapshot_id = str(valuation_snapshot["snapshot_id"])
    except Exception as exc:
        publication_error = "valuation_snapshot_persistence_failed"
        result.failed["__valuation_snapshot__"] = publication_error
        logger.exception("Failed to publish valuation snapshot after fund NAV sync")

    if callable(finish_run):
        success_count = len(result.refreshed)
        symbol_failure_count = sum(
            1 for symbol in due_symbols if symbol in result.failed
        )
        failure_count = symbol_failure_count + (1 if publication_error else 0)
        if publication_error or (failure_count and not success_count):
            status = "failed"
        elif failure_count:
            status = "partial_success"
        else:
            status = "success"
        finish_run(
            run_id=run_id,
            finished_at=datetime.now().isoformat(),
            status=status,
            success_count=success_count,
            failure_count=failure_count,
            error_message=publication_error,
            metadata={
                "requested_symbols": due_symbols,
                "refreshed_symbols": result.refreshed,
                "failed_symbols": sorted(
                    symbol for symbol in result.failed if not symbol.startswith("__")
                ),
                "valuation_snapshot_id": valuation_snapshot_id,
                "facts_persisted_only": True,
            },
        )
    return result
