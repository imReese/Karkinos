"""Quote identity, freshness, metadata, and hydration projections."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import HTTPException

from core.types import AssetClass
from data.market_data import is_fund_estimate_quote_source
from server.projections.portfolio_assets import normalize_asset_class
from server.projections.portfolio_quote_assets import (
    asset_class_for_position,
    asset_class_from_config,
    asset_class_from_ledger,
    asset_class_from_metadata,
    asset_class_from_watchlist,
    broker_cost_basis_evidence_by_symbol,
    broker_cost_basis_fields,
    normalize_asset_class_value,
    optional_float_attr,
    optional_float_value,
)
from server.projections.portfolio_read_snapshot import PortfolioReadSnapshotRejected
from server.projections.portfolio_read_snapshot_persistence import (
    portfolio_read_snapshot_for_state,
)
from server.projections.quote_status import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.projections.quote_status import quote_is_stale as _quote_is_stale
from server.projections.quote_status import quote_status as _quote_status
from server.projections.service import build_portfolio_projection_from_db
from server.projections.valuation_snapshot import (
    build_current_valuation_snapshot as build_current_valuation_projection,
)
from server.services.market_hours import get_shanghai_now, is_cn_trading_session
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger
from server.services.valuation_snapshot import (
    load_persisted_quote_rows,
    select_authoritative_quote_rows,
)

logger = logging.getLogger(__name__)


def has_position_ledger_entries(entries: object) -> bool:
    if not isinstance(entries, list):
        return False
    trade_types = {"trade_buy", "buy", "trade", "trade_sell", "sell"}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_type = str(entry.get("entry_type") or "").strip().lower()
        symbol = str(entry.get("symbol") or "").strip()
        if symbol and entry_type in trade_types:
            return True
    return False


def collect_latest_quote_timestamps(state) -> dict[str, str]:
    latest: dict[str, str] = {}
    read_snapshot = portfolio_read_snapshot_for_state(state)
    if read_snapshot is not None:
        for row in read_snapshot.published_valuation.get("quotes") or ():
            quote = adapt_persistent_quote_for_portfolio(dict(row))
            timestamp = quote.get("timestamp") or quote.get("quote_timestamp")
            symbol = quote.get("symbol")
            if symbol and timestamp:
                latest[str(symbol)] = str(timestamp)
        return latest
    db = state.db
    persistent_reader_available = db is not None and (
        hasattr(db, "list_latest_quotes_sync") or hasattr(db, "get_latest_quotes_sync")
    )
    if persistent_reader_available:
        for row in select_authoritative_quote_rows(load_persisted_quote_rows(db)):
            quote = adapt_persistent_quote_for_portfolio(row)
            timestamp = quote.get("timestamp")
            symbol = quote.get("symbol")
            if symbol and timestamp:
                latest[str(symbol)] = str(timestamp)
        return latest

    scheduler = state.scheduler
    if scheduler and getattr(scheduler, "latest_quotes", None):
        for symbol, quote in scheduler.latest_quotes.items():
            timestamp = quote.get("timestamp")
            if timestamp:
                latest[str(symbol)] = str(timestamp)

    return latest


def adapt_persistent_quote_for_portfolio(row: dict) -> dict:
    quote = dict(row)
    if quote.get("asset_class") in {None, ""} and quote.get("asset_type") not in {
        None,
        "",
    }:
        quote["asset_class"] = quote.get("asset_type")
    if quote.get("timestamp") in {None, ""} and quote.get("quote_timestamp") not in {
        None,
        "",
    }:
        quote["timestamp"] = quote.get("quote_timestamp")
    if (
        quote.get("previous_close") not in {None, ""}
        and quote.get("previous_close_date") in {None, ""}
        and quote.get("timestamp") not in {None, ""}
    ):
        quote["previous_close_date"] = quote.get("timestamp")
    if quote.get("source") in {None, ""} and quote.get("quote_source") not in {
        None,
        "",
    }:
        quote["source"] = quote.get("quote_source")
    if quote.get("provider") in {None, ""} and quote.get("provider_name") not in {
        None,
        "",
    }:
        quote["provider"] = quote.get("provider_name")

    metadata_json = quote.get("metadata_json")
    if metadata_json:
        try:
            metadata = json.loads(str(metadata_json))
        except (TypeError, ValueError):
            metadata = None
        if isinstance(metadata, dict):
            for key in (
                "display_name",
                "name",
                "asset_name",
                "market",
                "provider_symbol",
            ):
                value = metadata.get(key)
                if quote.get(key) in {None, ""} and value not in {None, ""}:
                    quote[key] = value
            if quote.get("source") in {None, ""} and metadata.get("source") not in {
                None,
                "",
            }:
                quote["source"] = metadata.get("source")
    return quote


def quote_market_timestamp(quote: dict) -> datetime | None:
    timestamps = [
        _parse_quote_timestamp(quote.get(key))
        for key in ("timestamp", "quote_timestamp")
    ]
    timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    return max(timestamps) if timestamps else None


def quote_merge_timestamp(quote: dict) -> datetime | None:
    timestamps = [
        _parse_quote_timestamp(quote.get(key)) for key in ("captured_at", "updated_at")
    ]
    timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    return max(timestamps) if timestamps else quote_market_timestamp(quote)


def merge_quote_identity(base: dict, candidate: dict) -> dict:
    base_timestamp = quote_market_timestamp(base)
    candidate_timestamp = quote_market_timestamp(candidate)
    if base_timestamp is not None and candidate_timestamp is not None:
        if candidate_timestamp > base_timestamp:
            primary = candidate
            secondary = base
        else:
            primary = base
            secondary = candidate
    else:
        base_timestamp = quote_merge_timestamp(base)
        candidate_timestamp = quote_merge_timestamp(candidate)
        if candidate_timestamp is not None and (
            base_timestamp is None or candidate_timestamp > base_timestamp
        ):
            primary = candidate
            secondary = base
        else:
            primary = base
            secondary = candidate

    merged = dict(primary)
    for key in (
        "asset_class",
        "display_name",
        "name",
        "asset_name",
        "market",
        "provider_symbol",
        "nav_date",
        "previous_close",
        "previous_close_date",
        "change",
        "change_percent",
        "day_change_value",
        "day_change_pct",
        "quote_status",
        "provider_status",
        "stale_reason",
    ):
        if merged.get(key) in {None, ""} and secondary.get(key) not in {None, ""}:
            merged[key] = secondary[key]
    return merged


def collect_latest_quotes(state) -> dict[str, dict]:
    """Read authoritative portfolio quotes from persisted observations.

    Runtime scheduler quotes are ingestion telemetry. When the database exposes
    a persistent quote reader, portfolio/account calculations must not merge
    those in-memory values into authoritative facts.
    """
    latest: dict[str, dict] = {}
    read_snapshot = portfolio_read_snapshot_for_state(state)
    if read_snapshot is not None:
        return quotes_from_valuation_snapshot(dict(read_snapshot.published_valuation))
    db = state.db
    persistent_reader_available = db is not None and (
        hasattr(db, "get_latest_quotes_sync") or hasattr(db, "list_latest_quotes_sync")
    )
    if persistent_reader_available:
        rows = select_authoritative_quote_rows(load_persisted_quote_rows(db))
        for row in rows:
            quote = adapt_persistent_quote_for_portfolio(row)
            symbol = quote.get("symbol")
            if not symbol:
                continue
            key = str(symbol)
            latest[key] = (
                merge_quote_identity(latest[key], quote) if key in latest else quote
            )
        return latest

    scheduler = state.scheduler
    if scheduler and getattr(scheduler, "latest_quotes", None):
        for symbol, quote in scheduler.latest_quotes.items():
            latest[str(symbol)] = quote
    return latest


def current_valuation_snapshot(
    state,
    *,
    now: datetime | None = None,
) -> dict:
    try:
        read_snapshot = portfolio_read_snapshot_for_state(state)
    except PortfolioReadSnapshotRejected as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if read_snapshot is not None:
        return dict(read_snapshot.published_valuation)
    snapshot = build_current_valuation_projection(state.db, persist=False, now=now)
    publication_reader = getattr(state.db, "get_runtime_control_sync", None)
    publication = (
        publication_reader("valuation_snapshot_publication")
        if callable(publication_reader)
        else None
    )
    published_snapshot_id = (
        publication.get("snapshot_id")
        if isinstance(publication, dict) and publication.get("status") == "ready"
        else None
    )
    if published_snapshot_id != snapshot["snapshot_id"]:
        raise HTTPException(
            status_code=503,
            detail=(
                "Current valuation facts have not been published as an "
                "immutable snapshot. Financial reads are blocked."
            ),
        )
    return snapshot


def quotes_from_valuation_snapshot(payload: dict) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for row in payload.get("quotes") or []:
        quote = adapt_persistent_quote_for_portfolio(row)
        symbol = quote.get("symbol")
        if not symbol:
            continue
        key = str(symbol)
        latest[key] = (
            merge_quote_identity(latest[key], quote) if key in latest else quote
        )
    return latest


def quote_age_seconds(quote: dict | None, now: datetime | None = None) -> int | None:
    timestamp = _parse_quote_timestamp(
        None if quote is None else quote.get("timestamp")
    )
    if timestamp is None:
        return None
    current = get_shanghai_now(now)
    return max(int((current - timestamp).total_seconds()), 0)


def quote_latest_price(quote: dict | None) -> float | None:
    if not quote or quote.get("price") in {None, ""}:
        return None
    return float(quote["price"])


def is_unconfirmed_fund_estimate(
    state,
    *,
    symbol: str,
    asset_class: str | None,
    quote: dict | None,
) -> bool:
    """Return whether a fund quote is an estimate without confirmed same-day NAV."""
    if normalize_asset_class(asset_class) != "fund":
        return False
    if not quote or quote.get("price") in {None, ""}:
        return False

    source = str(quote.get("quote_source") or quote.get("source") or "").strip().lower()
    if not is_fund_estimate_quote_source(source):
        return False

    if portfolio_read_snapshot_for_state(state) is not None:
        # A published valuation has already frozen same-day NAV/close evidence.
        # An estimate that remains in that snapshot is therefore unconfirmed;
        # do not perform a second mutable database lookup during the request.
        return True

    quote_timestamp = _parse_quote_timestamp(quote.get("timestamp"))
    if quote_timestamp is None:
        return True
    trade_date = quote_timestamp.date().isoformat()

    if state.db is None or not hasattr(state.db, "get_market_bar_on_date_sync"):
        return True
    market_bar = state.db.get_market_bar_on_date_sync(
        symbol,
        trade_date,
        instrument_type="open_end_fund",
    )
    if not market_bar:
        return True
    close = market_bar.get("close", market_bar.get("price"))
    return close in {None, ""}


def position_quote_presentation(
    state,
    *,
    symbol: str,
    asset_class: str | None,
    quote: dict | None,
    now: datetime | None = None,
) -> tuple[str, str | None]:
    quote_status = response_quote_status(state, quote, now=now)
    stale_reason = quote_stale_reason(state, quote, now=now)
    if is_unconfirmed_fund_estimate(
        state,
        symbol=symbol,
        asset_class=asset_class,
        quote=quote,
    ):
        return "stale", "confirmed_fund_nav_missing_estimate_only"
    return quote_status, stale_reason


def quote_source(state, quote: dict | None) -> str | None:
    if not quote:
        return None
    source = (
        quote.get("quote_source")
        or quote.get("source")
        or quote.get("provider_name")
        or quote.get("provider")
    )
    if source:
        return str(source)
    configured = getattr(state.config, "data_source", None)
    if configured:
        return str(configured)
    return None


def refresh_policy(now: datetime | None = None) -> str:
    current = get_shanghai_now(now)
    return "live" if is_cn_trading_session(current) else "cache_only"


def quote_stale_reason(
    state,
    quote: dict | None,
    *,
    now: datetime | None = None,
) -> str | None:
    if not quote or quote.get("price") in {None, ""}:
        return (
            str(quote.get("stale_reason"))
            if quote and quote.get("stale_reason")
            else "no_real_data_available"
        )
    if quote.get("stale_reason"):
        return str(quote["stale_reason"])

    timestamp = _parse_quote_timestamp(quote.get("timestamp"))
    if timestamp is None:
        return "quote_timestamp_missing"

    if _quote_status(state, quote, now=now) != "stale":
        return None

    policy = refresh_policy(now)
    if policy == "cache_only":
        return "market_closed_cache_only"

    return "quote_older_than_expected_session"


def response_quote_status(
    state,
    quote: dict | None,
    *,
    now: datetime | None = None,
) -> str:
    if not quote or quote.get("price") in {None, ""}:
        return "missing"
    return _quote_status(state, quote, now=now)


def using_persistent_cache(quote: dict | None) -> bool:
    return bool(
        quote
        and (
            quote.get("using_persistent_cache")
            or quote.get("captured_reason") == "persistent_cache"
            or quote.get("quote_status") == "stale"
        )
    )


def can_refresh_quotes(state, now: datetime | None = None) -> bool:
    return bool(hasattr(state.config, "data_source") and is_cn_trading_session(now))


def store_runtime_quote(state, symbol: str, quote: dict) -> None:
    scheduler = state.scheduler
    if scheduler is None:
        return
    publish = getattr(scheduler, "publish_runtime_quote", None)
    if not callable(publish):
        return
    publish(symbol, quote)


def hydrate_missing_position_quotes(
    state,
    portfolio,
    instruments: dict,
    *,
    allow_remote_refresh: bool = False,
) -> tuple[object, dict, bool]:
    if portfolio is None:
        return portfolio, instruments, False
    if not allow_remote_refresh:
        return portfolio, instruments, False

    latest_quotes = collect_latest_quotes(state)
    refresh_needed: list[tuple[str, AssetClass]] = []
    now = get_shanghai_now()
    can_refresh = can_refresh_quotes(state, now)
    for sym in portfolio.positions:
        symbol = str(sym)
        quote = latest_quotes.get(symbol)
        if quote:
            is_stale = _quote_is_stale(
                quote,
                now=now,
                live_poll_interval=getattr(state.config, "live_poll_interval", 60),
            )
            if not is_stale or not can_refresh:
                continue
        asset_class = asset_class_for_position(symbol, quote, instruments, state)
        if asset_class is None:
            continue
        refresh_needed.append((symbol, asset_class))

    if not refresh_needed:
        return portfolio, instruments, False

    from server.services.market_refresh import fetch_latest_snapshot

    hydrated = False
    for symbol, asset_class in refresh_needed:
        try:
            snapshot = fetch_latest_snapshot(state, symbol, asset_class)
        except Exception:
            logger.warning(
                "Failed to refresh stale quote for %s", symbol, exc_info=True
            )
            continue
        if snapshot:
            latest_quotes[symbol] = snapshot
            store_runtime_quote(state, symbol, snapshot)
            hydrated = True

    if not hydrated or state.db is None:
        return portfolio, instruments, hydrated

    ledger_entries = (
        state.db.get_ledger_entries_sync(limit=1, offset=0)
        if hasattr(state.db, "get_ledger_entries_sync")
        else []
    )
    if has_position_ledger_entries(ledger_entries):
        rebuilt_projection = build_portfolio_projection_from_db(
            state.db,
            initial_cash=0,
            latest_quotes=latest_quotes,
        )
        return rebuilt_projection, instruments, True

    rebuilt = rebuild_portfolio_from_ledger(
        state.config,
        state.db,
        latest_quotes=latest_quotes,
    )
    return rebuilt.portfolio, rebuilt.instruments, True
