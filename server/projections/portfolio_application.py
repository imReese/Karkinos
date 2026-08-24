"""Application projection extracted from the HTTP delivery adapter."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from core.types import AssetClass, Symbol
from data.market_data import is_fund_estimate_quote_source
from server.models import (
    AccountOverview,
    AccountStateResponse,
    AllocationGroup,
    AllocationItem,
    ClosedPositionResponse,
    PortfolioSnapshot,
    PositionEvidenceReviewResponse,
    PositionResponse,
)
from server.projections.quote_status import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.projections.quote_status import quote_is_stale as _quote_is_stale
from server.projections.quote_status import quote_status as _quote_status
from server.projections.service import (
    build_portfolio_projection_from_db,
)
from server.services.account_state import build_account_state_projection
from server.services.asset_metadata import resolve_asset_metadata
from server.services.daily_performance import (
    build_position_daily_context,
    mark_position_daily,
)
from server.services.market_hours import get_shanghai_now, is_cn_trading_session
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger
from server.services.position_presence import (
    classify_position_presence,
)
from server.services.risk_engine import build_risk_summary
from server.services.valuation_snapshot import (
    build_current_valuation_snapshot,
    load_persisted_quote_rows,
    select_authoritative_quote_rows,
    valuation_identity_fields,
)

logger = logging.getLogger(__name__)

_FUND_SUBSCRIPTION_CUTOFF = time(15, 0)

_SH_TZ = ZoneInfo("Asia/Shanghai")

_ASSET_CLASS_LABELS = {
    "stock": "股票",
    "fund": "基金",
    "etf": "ETF",
    "gold": "黄金",
    "bond": "债券",
    "cash": "现金",
}


def normalize_asset_class(value: str | None) -> str:
    if not value:
        return "other"
    normalized = str(value).strip().lower()
    if normalized in {"stock", "fund", "etf", "gold", "bond", "cash"}:
        return normalized
    return "other"


def ensure_asset_config(
    state,
    *,
    symbol: str,
    asset_class: str,
    display_name: str | None = None,
) -> None:
    db = getattr(state, "db", None)
    existing_display_name = None
    list_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    if callable(list_watchlist):
        try:
            existing_watchlist = next(
                (
                    asset
                    for asset in list_watchlist() or []
                    if str(asset.get("symbol") or "").strip().lower()
                    == symbol.strip().lower()
                ),
                None,
            )
        except Exception:
            existing_watchlist = None
        if existing_watchlist is not None:
            existing_display_name = (
                str(existing_watchlist.get("display_name") or "").strip() or None
            )

    upsert_watchlist = getattr(db, "upsert_watchlist_asset_sync", None)
    if callable(upsert_watchlist) and existing_display_name is None:
        upsert_watchlist(
            symbol=symbol,
            asset_class=asset_class,
            display_name=display_name or symbol,
            source="trade",
        )

    existing_metadata = None
    get_metadata = getattr(db, "get_instrument_metadata_sync", None)
    if callable(get_metadata):
        try:
            existing_metadata = get_metadata(symbol, asset_class)
            if existing_metadata is None:
                existing_metadata = get_metadata(symbol)
        except Exception:
            existing_metadata = None
    upsert_metadata = getattr(db, "upsert_instrument_metadata_sync", None)
    if callable(upsert_metadata) and existing_metadata is None:
        upsert_metadata(
            symbol=symbol,
            asset_type=asset_class,
            display_name=display_name or existing_display_name or symbol,
            provider_symbol=symbol,
            source="trade",
        )


def resolve_fund_buy_fill(
    state,
    *,
    symbol: str,
    timestamp: str,
    gross_amount: float,
    commission: float,
) -> dict:
    from core.types import AssetClass, BarFrequency, Symbol
    from data.manager import build_sources

    submitted_at = datetime.fromisoformat(timestamp)
    target_date = submitted_at.date()
    if submitted_at.time() >= _FUND_SUBSCRIPTION_CUTOFF:
        target_date += timedelta(days=1)

    sources = build_sources(
        data_source=getattr(state.config, "data_source", "akshare"),
        tushare_token=getattr(state.config, "tushare_token", ""),
    )
    akshare = sources["akshare"]
    symbol_obj = Symbol(symbol.strip())
    display_name = (
        akshare._resolve_open_end_fund_name(symbol_obj)
        if hasattr(akshare, "_resolve_open_end_fund_name")
        else str(symbol_obj)
    ) or str(symbol_obj)
    canonical_symbol = (
        akshare._resolve_open_end_fund_code(symbol_obj)
        if hasattr(akshare, "_resolve_open_end_fund_code")
        else str(symbol_obj)
    ) or str(symbol_obj)

    start = datetime.combine(submitted_at.date() - timedelta(days=1), time.min)
    end = datetime.combine(submitted_at.date() + timedelta(days=10), time.max)
    bars = akshare.fetch_bars(
        Symbol(canonical_symbol),
        start=start,
        end=end,
        frequency=BarFrequency.DAILY,
        asset_class=AssetClass.FUND,
    )
    if bars.empty:
        raise ValueError("No fund NAV history available from AKShare")

    eligible = bars[bars["timestamp"].dt.date >= target_date].sort_values("timestamp")
    latest_available = bars["timestamp"].max().date()
    if eligible.empty:
        raise LookupError(
            f"Fund NAV for target trade date {target_date.isoformat()} is not published yet "
            f"(latest available {latest_available.isoformat()})."
        )

    confirmed = eligible.iloc[0]
    confirmed_trade_date = confirmed["timestamp"].date().isoformat()
    confirmed_nav = float(confirmed["close"])
    net_amount = gross_amount - commission
    if net_amount <= 0:
        raise ValueError("Net subscription amount must be positive")
    quantity = net_amount / confirmed_nav
    return {
        "symbol": canonical_symbol,
        "display_name": display_name,
        "price": confirmed_nav,
        "quantity": quantity,
        "confirmed_trade_date": confirmed_trade_date,
        "gross_amount": gross_amount,
        "target_trade_date": target_date.isoformat(),
    }


def confirm_pending_fund_orders(state) -> int:
    """Try to convert published pending fund subscriptions into normal trades."""
    if state.db is None or not hasattr(state.db, "get_pending_fund_orders_sync"):
        return 0

    confirmed_count = 0
    for order in state.db.get_pending_fund_orders_sync(status="pending"):
        try:
            resolved = resolve_fund_buy_fill(
                state,
                symbol=order["symbol"],
                timestamp=order["submitted_at"],
                gross_amount=float(order["amount"]),
                commission=float(order.get("commission") or 0.0),
            )
        except (LookupError, ValueError):
            continue

        note_parts = [
            order.get("note") or "",
            f"Auto-confirmed pending fund subscription: gross_amount={resolved['gross_amount']:.2f}",
            f"confirmed_trade_date={resolved['confirmed_trade_date']}",
            f"confirmed_nav={resolved['price']:.6f}",
        ]
        trade_id = state.db.add_trade_sync(
            timestamp=order["submitted_at"],
            symbol=resolved["symbol"],
            direction="buy",
            quantity=resolved["quantity"],
            price=resolved["price"],
            commission=float(order.get("commission") or 0.0),
            asset_class="fund",
            note=" | ".join(part for part in note_parts if part),
        )
        state.db.insert_ledger_entry_sync(
            entry_type="trade_buy",
            timestamp=order["submitted_at"],
            amount=resolved["quantity"] * resolved["price"],
            symbol=resolved["symbol"],
            direction="buy",
            quantity=resolved["quantity"],
            price=resolved["price"],
            commission=float(order.get("commission") or 0.0),
            asset_class="fund",
            note=" | ".join(part for part in note_parts if part),
            source="portfolio_trade",
            source_ref=f"trade:{trade_id}",
        )
        state.db.mark_pending_fund_order_confirmed_sync(
            order_id=int(order["id"]),
            trade_id=trade_id,
            confirmed_nav=resolved["price"],
            confirmed_quantity=resolved["quantity"],
            confirmed_trade_date=resolved["confirmed_trade_date"],
        )
        ensure_asset_config(
            state,
            symbol=resolved["symbol"],
            asset_class="fund",
            display_name=resolved["display_name"],
        )
        confirmed_count += 1
    return confirmed_count


def build_grouped_allocation(
    allocation: list[AllocationItem], total_equity: float
) -> list[AllocationGroup]:
    """按 asset_class 聚合 allocation 列表。"""
    groups: dict[str, list[AllocationItem]] = defaultdict(list)
    for item in allocation:
        groups[item.asset_class].append(item)

    result = []
    for ac, items in groups.items():
        group_value = sum(i.value for i in items)
        result.append(
            AllocationGroup(
                asset_class=ac,
                name=_ASSET_CLASS_LABELS.get(ac, ac),
                value=group_value,
                weight=group_value / total_equity if total_equity > 0 else 0,
                items=items,
            )
        )
    # 现金排第一，其余按市值降序
    result.sort(key=lambda g: (g.asset_class != "cash", -g.value))
    return result


def parse_fee_breakdown(value) -> dict | None:
    if not value:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def collect_latest_quote_timestamps(state) -> dict[str, str]:
    latest: dict[str, str] = {}
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


def current_valuation_snapshot(state) -> dict:
    snapshot = build_current_valuation_snapshot(state.db, persist=False)
    publication_reader = getattr(state.db, "get_runtime_control_sync", None)
    if callable(publication_reader):
        publication = publication_reader("valuation_snapshot_publication")
        published_snapshot_id = (
            publication.get("snapshot_id")
            if isinstance(publication, dict) and publication.get("status") == "ready"
            else None
        )
        if (
            published_snapshot_id is not None
            and published_snapshot_id != snapshot["snapshot_id"]
        ):
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

    quote_timestamp = _parse_quote_timestamp(quote.get("timestamp"))
    if quote_timestamp is None:
        return True
    trade_date = quote_timestamp.date().isoformat()

    if state.db is None or not hasattr(state.db, "get_market_bar_on_date_sync"):
        return True
    market_bar = state.db.get_market_bar_on_date_sync(symbol, trade_date)
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
) -> tuple[str, str | None]:
    quote_status = response_quote_status(state, quote)
    stale_reason = quote_stale_reason(state, quote)
    if is_unconfirmed_fund_estimate(
        state,
        symbol=symbol,
        asset_class=asset_class,
        quote=quote,
    ):
        return "stale", "confirmed_fund_nav_missing_estimate_only"
    return quote_status, stale_reason


def optional_float_attr(obj, name: str) -> float | None:
    return optional_float_value(getattr(obj, name, None))


def optional_float_value(value) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def broker_cost_basis_evidence_by_symbol(
    state,
    symbols: set[str],
) -> dict[str, dict[str, object]]:
    if not symbols:
        return {}
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        return {}

    try:
        from account_truth.broker_evidence import BrokerEvidenceRepository

        repository = BrokerEvidenceRepository(db_path)
        evidence_by_symbol: dict[str, dict[str, object]] = {}
        for import_run in repository.list_import_runs(limit=50):
            for event in reversed(repository.list_events(import_run.import_run_id)):
                symbol = str(event.symbol)
                if (
                    symbol not in symbols
                    or symbol in evidence_by_symbol
                    or event.event_type != "position_snapshot"
                    or event.is_row_duplicate
                ):
                    continue
                unit_cost = optional_float_value(event.cost_basis)
                if unit_cost is None:
                    continue
                evidence_by_symbol[symbol] = {
                    "unit_cost": unit_cost,
                    "method": event.cost_basis_method or "broker_remaining_cost",
                    "import_run_id": import_run.import_run_id,
                }
            if symbols.issubset(evidence_by_symbol):
                break
        return evidence_by_symbol
    except Exception:
        logger.debug("Unable to hydrate broker cost-basis evidence", exc_info=True)
        return {}


def broker_cost_basis_fields(
    pos,
    evidence: dict[str, object] | None,
    *,
    quantity: float,
    avg_cost: float,
) -> dict[str, object]:
    unit_cost = optional_float_attr(pos, "broker_displayed_unit_cost")
    if unit_cost is None and evidence is not None:
        unit_cost = optional_float_value(evidence.get("unit_cost"))

    displayed_cost_basis = optional_float_attr(pos, "broker_displayed_cost_basis")
    if displayed_cost_basis is None and unit_cost is not None:
        displayed_cost_basis = unit_cost * quantity

    difference = optional_float_attr(pos, "broker_cost_basis_difference")
    if difference is None and displayed_cost_basis is not None:
        difference = displayed_cost_basis - quantity * avg_cost

    method = getattr(pos, "broker_cost_basis_method", None)
    if method is None and evidence is not None:
        method = evidence.get("method")

    status = getattr(pos, "broker_cost_basis_status", None)
    if status is None and unit_cost is not None:
        status = "available"

    return {
        "broker_displayed_unit_cost": unit_cost,
        "broker_displayed_cost_basis": displayed_cost_basis,
        "broker_cost_basis_difference": difference,
        "broker_cost_basis_method": method,
        "broker_cost_basis_status": status,
    }


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


def response_quote_status(state, quote: dict | None) -> str:
    if not quote or quote.get("price") in {None, ""}:
        return "missing"
    return _quote_status(state, quote)


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


def asset_class_from_config(state, symbol: str) -> str | None:
    """Legacy fallback for old config.json assets; DB sources are authoritative."""
    for asset in getattr(state.config, "assets", []) or []:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("symbol") or "").strip() != symbol:
            continue
        asset_class = asset.get("asset_class") or asset.get("asset_type")
        if asset_class not in {None, ""}:
            return str(asset_class)
    return None


def asset_class_from_watchlist(state, symbol: str) -> str | None:
    db = getattr(state, "db", None)
    list_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    if not callable(list_watchlist):
        return None
    try:
        rows = list_watchlist()
    except Exception:
        logger.warning("Failed to read watchlist assets for %s", symbol, exc_info=True)
        return None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").strip() != symbol:
            continue
        asset_class = row.get("asset_class") or row.get("asset_type")
        if asset_class not in {None, ""}:
            return str(asset_class)
    return None


def asset_class_from_metadata(state, symbol: str) -> str | None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "get_instrument_metadata_sync"):
        return None
    try:
        metadata = db.get_instrument_metadata_sync(symbol)
    except Exception:
        logger.warning(
            "Failed to read instrument metadata for %s", symbol, exc_info=True
        )
        return None
    if not metadata:
        return None
    asset_class = metadata.get("asset_type") or metadata.get("asset_class")
    return None if asset_class in {None, ""} else str(asset_class)


def asset_class_from_ledger(state, symbol: str) -> str | None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "get_ledger_entries_sync"):
        return None

    offset = 0
    batch_size = 500
    latest_asset_class: str | None = None
    while True:
        rows = db.get_ledger_entries_sync(limit=batch_size, offset=offset)
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("symbol") or "").strip() != symbol:
                continue
            asset_class = row.get("asset_class")
            if asset_class not in {None, ""}:
                latest_asset_class = str(asset_class)
        if len(rows) < batch_size:
            break
        offset += batch_size
    return latest_asset_class


def asset_class_for_position(
    symbol: str, quote: dict | None, instruments: dict, state=None
) -> AssetClass | None:
    raw_asset_class = (quote or {}).get("asset_class")
    if not raw_asset_class and instruments:
        instrument = instruments.get(Symbol(symbol)) or instruments.get(symbol)
        raw_asset_class = getattr(
            getattr(instrument, "asset_class", None), "value", None
        )
    if not raw_asset_class and state is not None:
        raw_asset_class = (
            asset_class_from_metadata(state, symbol)
            or asset_class_from_watchlist(state, symbol)
            or asset_class_from_ledger(state, symbol)
            or asset_class_from_config(state, symbol)
        )

    normalized = normalize_asset_class_value(raw_asset_class)
    if normalized == "etf":
        normalized = AssetClass.FUND.value

    try:
        return AssetClass(normalized)
    except ValueError:
        return None


def store_runtime_quote(state, symbol: str, quote: dict) -> None:
    scheduler = state.scheduler
    if scheduler is None:
        return

    if hasattr(scheduler, "_latest_quotes"):
        scheduler._latest_quotes[symbol] = quote
        return

    latest_quotes = getattr(scheduler, "latest_quotes", None)
    if isinstance(latest_quotes, dict):
        latest_quotes[symbol] = quote


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
            initial_cash=state.config.initial_cash,
            latest_quotes=latest_quotes,
        )
        return rebuilt_projection, instruments, True

    rebuilt = rebuild_portfolio_from_ledger(
        state.config,
        state.db,
        latest_quotes=latest_quotes,
    )
    return rebuilt.portfolio, rebuilt.instruments, True


def resolve_live_holding_baseline(
    state, symbol: str, latest_quote: dict | None
) -> tuple[float | None, str | None, str]:
    latest_timestamp = _parse_quote_timestamp(
        None if latest_quote is None else latest_quote.get("timestamp")
    )
    trade_date = (
        latest_timestamp.date().isoformat()
        if latest_timestamp is not None
        else datetime.now().date().isoformat()
    )

    if latest_quote:
        previous_close = latest_quote.get("previous_close")
        previous_close_date = latest_quote.get("previous_close_date")
        if previous_close not in {None, 0, ""}:
            return (
                float(previous_close),
                None if previous_close_date in {None, ""} else str(previous_close_date),
                str(latest_quote.get("previous_close_source") or "previous_close"),
            )

        if "valuation_baseline_status" in latest_quote:
            return None, None, "snapshot_baseline_unavailable"

    if state.db is not None and hasattr(
        state.db, "get_latest_market_bar_before_date_sync"
    ):
        market_bar = state.db.get_latest_market_bar_before_date_sync(symbol, trade_date)
        if market_bar:
            return (
                float(market_bar.get("close", market_bar.get("price"))),
                market_bar.get("trade_date")
                or str(market_bar.get("timestamp", "")).split("T")[0],
                "market_bar_close",
            )

    if state.db is not None and hasattr(state.db, "get_latest_daily_close_before_sync"):
        daily_close = state.db.get_latest_daily_close_before_sync(symbol, trade_date)
        if daily_close:
            return (
                float(daily_close["close_price"]),
                daily_close.get("trade_date"),
                "daily_close",
            )

    if state.db is not None and hasattr(state.db, "get_latest_quote_before_date_sync"):
        fallback_quote = state.db.get_latest_quote_before_date_sync(symbol, trade_date)
        if fallback_quote:
            if hasattr(state.db, "save_daily_close_snapshot_sync"):
                state.db.save_daily_close_snapshot_sync(
                    symbol=symbol,
                    asset_class=str(fallback_quote.get("asset_class") or "stock"),
                    trade_date=str(fallback_quote["timestamp"]).split("T")[0],
                    close_price=float(fallback_quote["price"]),
                    source="quote_fallback",
                )
            return (
                float(fallback_quote["price"]),
                fallback_quote.get("timestamp"),
                "fallback_close",
            )

    return None, None, "unavailable"


def ledger_entry_shanghai_date(entry: dict) -> date | None:
    timestamp = entry.get("timestamp")
    if timestamp in {None, ""}:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SH_TZ)
    return parsed.astimezone(_SH_TZ).date()


def read_daily_ledger_entries(state, *, batch_size: int = 500) -> list[dict]:
    db = state.db
    if db is None or not hasattr(db, "get_ledger_entries_sync"):
        return []

    entries: list[dict] = []
    offset = 0
    while True:
        batch = db.get_ledger_entries_sync(limit=batch_size, offset=offset)
        if not batch:
            break
        entries.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size
    return entries


def same_day_buy_lots(
    state,
    *,
    symbol: str,
    trade_day: date,
    ledger_entries: list[dict] | None = None,
) -> list[dict[str, float | datetime]]:
    lots: list[dict[str, float | datetime]] = []
    resolved_entries = (
        read_daily_ledger_entries(state) if ledger_entries is None else ledger_entries
    )
    for entry in resolved_entries:
        if (
            str(entry.get("symbol") or "") != symbol
            or str(entry.get("entry_type") or "").lower() != "trade_buy"
            or ledger_entry_shanghai_date(entry) != trade_day
        ):
            continue
        quantity = entry.get("quantity")
        price = entry.get("price")
        if quantity in {None, ""} or price in {None, ""}:
            continue
        quantity_value = float(quantity)
        if quantity_value <= 0:
            continue
        timestamp = _parse_quote_timestamp(entry.get("timestamp"))
        if timestamp is None:
            continue
        trade_cost = quantity_value * float(price)
        trade_cost += ledger_entry_trade_total_fee(entry)
        lots.append(
            {
                "timestamp": timestamp.astimezone(_SH_TZ),
                "quantity": quantity_value,
                "price": float(price),
                "total_cost": trade_cost,
                "avg_cost": trade_cost / quantity_value,
            }
        )

    return sorted(lots, key=lambda lot: lot["timestamp"])


def ledger_entry_trade_total_fee(entry: dict) -> float:
    breakdown = (
        parse_fee_breakdown(
            entry.get("fee_breakdown_json") or entry.get("fee_breakdown")
        )
        or {}
    )
    total_fee = breakdown.get("total_fee")
    if total_fee not in {None, ""}:
        return abs(float(total_fee))

    commission = breakdown.get("commission")
    total = abs(
        float(commission)
        if commission not in {None, ""}
        else float(entry.get("commission") or 0.0)
    )
    for aliases in (
        ("subscription_fee",),
        ("redemption_fee",),
        ("stamp_tax", "tax"),
        ("transfer_fee",),
        ("other_fees",),
        ("surcharge_fee",),
        ("exchange_clearing_fee",),
    ):
        for key in aliases:
            value = breakdown.get(key)
            if value not in {None, ""}:
                total += abs(float(value))
                break
    return total


def same_day_sell_lots(
    state,
    *,
    symbol: str,
    trade_day: date,
    ledger_entries: list[dict] | None = None,
) -> list[dict[str, float | datetime]]:
    lots: list[dict[str, float | datetime]] = []
    resolved_entries = (
        read_daily_ledger_entries(state) if ledger_entries is None else ledger_entries
    )
    for entry in resolved_entries:
        if (
            str(entry.get("symbol") or "") != symbol
            or str(entry.get("entry_type") or "").lower() != "trade_sell"
            or ledger_entry_shanghai_date(entry) != trade_day
        ):
            continue
        quantity = entry.get("quantity")
        price = entry.get("price")
        if quantity in {None, ""} or price in {None, ""}:
            continue
        quantity_value = float(quantity)
        if quantity_value <= 0:
            continue
        timestamp = _parse_quote_timestamp(entry.get("timestamp"))
        if timestamp is None:
            continue
        net_cash_impact = entry.get("net_cash_impact")
        net_proceeds = (
            float(net_cash_impact)
            if net_cash_impact not in {None, ""}
            else quantity_value * float(price) - ledger_entry_trade_total_fee(entry)
        )
        lots.append(
            {
                "timestamp": timestamp.astimezone(_SH_TZ),
                "quantity": quantity_value,
                "price": float(price),
                "net_proceeds": net_proceeds,
            }
        )

    return sorted(lots, key=lambda lot: lot["timestamp"])


def resolve_position_today_change(
    state,
    *,
    symbol: str,
    quantity: float,
    avg_cost: float,
    latest_quote: dict | None,
    latest_price_value: float | None,
    ledger_entries: list[dict] | None = None,
) -> tuple[float | None, float | None, float | None, str | None, str]:
    baseline_price, baseline_timestamp, baseline_source = resolve_live_holding_baseline(
        state, symbol, latest_quote
    )
    latest_timestamp = _parse_quote_timestamp(
        None if latest_quote is None else latest_quote.get("timestamp")
    )
    resolved_entries = (
        read_daily_ledger_entries(state) if ledger_entries is None else ledger_entries
    )
    shanghai_today = get_shanghai_now().date()
    has_today_trade = any(
        str(entry.get("symbol") or "") == symbol
        and str(entry.get("entry_type") or "").lower() in {"trade_buy", "trade_sell"}
        and ledger_entry_shanghai_date(entry) == shanghai_today
        for entry in resolved_entries
    )
    trade_day = (
        shanghai_today
        if has_today_trade or latest_timestamp is None
        else latest_timestamp.date()
    )
    buy_lots = same_day_buy_lots(
        state,
        symbol=symbol,
        trade_day=trade_day,
        ledger_entries=resolved_entries,
    )
    sell_lots = same_day_sell_lots(
        state,
        symbol=symbol,
        trade_day=trade_day,
        ledger_entries=resolved_entries,
    )
    context = build_position_daily_context(
        quantity=quantity,
        previous_close=baseline_price,
        same_day_buy_lots=buy_lots,
        same_day_sell_lots=sell_lots,
    )
    reference_price = (
        latest_price_value
        if latest_price_value is not None
        else (float(context.sell_lots[-1].price) if context.sell_lots else avg_cost)
    )
    mark = mark_position_daily(context, price=reference_price)
    if (context.lots or context.sell_lots) and context.status == "complete":
        baseline_price = context.baseline_price
        baseline_timestamp = trade_day.isoformat()
        baseline_source = context.source
    elif context.status != "complete":
        baseline_source = context.source

    return (
        mark.today_change,
        mark.today_change_pct,
        baseline_price,
        baseline_timestamp,
        baseline_source,
    )


def has_rows(rows: list[dict]) -> bool:
    return len(rows) > 0


def resolve_projection_sources(
    state,
    *,
    latest_quotes: dict[str, dict] | None = None,
) -> tuple[object | None, dict]:
    scheduler = state.scheduler
    portfolio = scheduler.portfolio if scheduler else None
    instruments = scheduler.instruments if scheduler else {}

    if state.db is None:
        return portfolio, instruments

    latest_quotes = (
        collect_latest_quotes(state) if latest_quotes is None else latest_quotes
    )
    ledger_entries = (
        state.db.get_ledger_entries_sync(limit=50, offset=0)
        if hasattr(state.db, "get_ledger_entries_sync")
        else []
    )
    if has_rows(ledger_entries) and (
        portfolio is None or has_position_ledger_entries(ledger_entries)
    ):
        return (
            build_portfolio_projection_from_db(
                state.db,
                initial_cash=state.config.initial_cash,
                latest_quotes=latest_quotes,
            ),
            {},
        )

    legacy_cash_flows = (
        state.db.get_cash_flows_sync(limit=1, offset=0)
        if hasattr(state.db, "get_cash_flows_sync")
        else []
    )
    legacy_trades = (
        state.db.get_trades_sync(limit=1, offset=0)
        if hasattr(state.db, "get_trades_sync")
        else []
    )

    if has_rows(legacy_cash_flows) or has_rows(legacy_trades):
        rebuilt = rebuild_portfolio_from_ledger(
            state.config,
            state.db,
            latest_quotes=latest_quotes,
        )
        return rebuilt.portfolio, rebuilt.instruments

    if portfolio is not None:
        return portfolio, instruments

    return None, {}


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


def normalize_asset_class_value(value) -> str:
    if hasattr(value, "value"):
        return normalize_asset_class(getattr(value, "value", None))
    return normalize_asset_class(str(value) if value is not None else None)


def snapshot_quote_status(snapshot: PortfolioSnapshot) -> str:
    if any(position.quote_status == "missing" for position in snapshot.positions):
        return "missing"
    if any(position.quote_status == "stale" for position in snapshot.positions):
        return "stale"
    return "live"


def snapshot_quote_age_seconds(snapshot: PortfolioSnapshot) -> int | None:
    ages = [
        position.quote_age_seconds
        for position in snapshot.positions
        if position.quote_age_seconds is not None
    ]
    return max(ages) if ages else None


def snapshot_stale_reason(snapshot: PortfolioSnapshot) -> str | None:
    for position in snapshot.positions:
        if position.quote_status == "stale" and position.stale_reason:
            return position.stale_reason
        if position.quote_status == "missing" and position.stale_reason:
            return position.stale_reason
    return None


def snapshot_quote_source(snapshot: PortfolioSnapshot) -> str | None:
    for position in snapshot.positions:
        if position.quote_source:
            return position.quote_source
    return None


def snapshot_uses_persistent_cache(snapshot: PortfolioSnapshot) -> bool:
    return any(position.using_persistent_cache for position in snapshot.positions)


def with_overview_quote_metadata(
    overview: AccountOverview,
    snapshot: PortfolioSnapshot,
) -> AccountOverview:
    return overview.model_copy(
        update={
            "valuation_timestamp": get_shanghai_now().isoformat(),
            "quote_status": snapshot_quote_status(snapshot),
            "quote_age_seconds": snapshot_quote_age_seconds(snapshot),
            "quote_source": snapshot_quote_source(snapshot),
            "stale_reason": snapshot_stale_reason(snapshot),
            "refresh_policy": refresh_policy(),
            "using_persistent_cache": snapshot_uses_persistent_cache(snapshot),
        }
    )


async def build_portfolio_snapshot(state) -> PortfolioSnapshot:
    """Build the canonical Portfolio projection from persisted application facts."""
    scheduler = state.scheduler
    valuation_snapshot = current_valuation_snapshot(state)
    latest_quotes = quotes_from_valuation_snapshot(valuation_snapshot)
    portfolio, instruments = resolve_projection_sources(
        state,
        latest_quotes=latest_quotes,
    )
    portfolio, instruments, _ = hydrate_missing_position_quotes(
        state,
        portfolio,
        instruments,
    )

    if portfolio is None:
        return PortfolioSnapshot(
            cash=0.0,
            total_equity=0.0,
            total_deposits=0.0,
            positions=[],
            allocation=[],
            allocation_grouped=[],
            realized_pnl_total=0.0,
            **valuation_identity_fields(valuation_snapshot),
        )

    broker_cost_basis_evidence = broker_cost_basis_evidence_by_symbol(
        state,
        {str(symbol) for symbol in portfolio.positions},
    )
    positions: list[PositionResponse] = []
    closed_positions: list[ClosedPositionResponse] = []
    position_review_items: list[PositionEvidenceReviewResponse] = []
    realized_pnl_total = 0.0
    daily_ledger_entries = read_daily_ledger_entries(state)
    ledger_asset_classes: dict[str, str] = {}
    for entry in daily_ledger_entries:
        ledger_symbol = str(entry.get("symbol") or "").strip()
        ledger_asset_class = str(entry.get("asset_class") or "").strip()
        if ledger_symbol and ledger_asset_class:
            ledger_asset_classes.setdefault(ledger_symbol, ledger_asset_class)
    for sym, pos in portfolio.positions.items():
        symbol = str(sym)
        quote = latest_quotes.get(symbol)
        instrument = instruments.get(Symbol(symbol)) if instruments else None
        asset_class = normalize_asset_class(
            (quote or {}).get("asset_class")
            or getattr(getattr(instrument, "asset_class", None), "value", None)
            or ledger_asset_classes.get(symbol)
        )
        metadata = resolve_asset_metadata(
            state,
            symbol,
            asset_class=asset_class,
            quote=quote,
            fallback_name=getattr(instrument, "name", None) or symbol,
        )
        quantity = float(pos.quantity)
        avg_cost = float(pos.avg_cost)
        latest_price_value = quote_latest_price(quote)
        (
            today_change,
            today_change_pct,
            baseline_price,
            baseline_timestamp,
            baseline_source,
        ) = resolve_position_today_change(
            state,
            symbol=symbol,
            quantity=quantity,
            avg_cost=avg_cost,
            latest_quote=quote,
            latest_price_value=latest_price_value,
            ledger_entries=daily_ledger_entries,
        )
        quote_status, stale_reason = position_quote_presentation(
            state,
            symbol=symbol,
            asset_class=metadata.asset_class,
            quote=quote,
        )
        cost_basis_fields = broker_cost_basis_fields(
            pos,
            broker_cost_basis_evidence.get(symbol),
            quantity=quantity,
            avg_cost=avg_cost,
        )
        response_position = PositionResponse(
            symbol=symbol,
            name=metadata.display_name,
            display_name=metadata.display_name,
            asset_class=metadata.asset_class,
            quantity=quantity,
            available_qty=float(pos.available_qty),
            frozen_qty=float(pos.frozen_qty),
            avg_cost=avg_cost,
            **cost_basis_fields,
            latest_price=latest_price_value,
            market_value=float(pos.market_value),
            unrealized_pnl=float(pos.unrealized_pnl),
            realized_pnl=float(pos.realized_pnl),
            commission_paid=float(pos.commission_paid),
            today_change=today_change,
            today_change_pct=today_change_pct,
            baseline_price=baseline_price,
            baseline_timestamp=baseline_timestamp,
            baseline_source=baseline_source,
            quote_timestamp=None if quote is None else quote.get("timestamp"),
            quote_status=quote_status,
            quote_source=quote_source(state, quote),
            quote_age_seconds=quote_age_seconds(quote),
            stale_reason=stale_reason,
            refresh_policy=refresh_policy(),
            using_persistent_cache=using_persistent_cache(quote),
            nav_date=None if quote is None else quote.get("nav_date"),
        )
        realized_pnl_total += response_position.realized_pnl
        presence, reason_codes = classify_position_presence(pos)
        if presence == "current":
            positions.append(response_position)
        elif presence == "closed":
            closed_positions.append(
                ClosedPositionResponse(
                    **response_position.model_dump(),
                    closed_at=getattr(pos, "closed_at", None),
                )
            )
        else:
            position_review_items.append(
                PositionEvidenceReviewResponse(
                    reason_codes=reason_codes,
                    position=response_position,
                )
            )

    total_equity = float(portfolio.cash)
    for pos in positions:
        total_equity += pos.market_value

    allocation: list[AllocationItem] = []
    if total_equity > 0:
        allocation.append(
            AllocationItem(
                symbol="CASH",
                name="现金",
                weight=float(portfolio.cash) / total_equity,
                value=float(portfolio.cash),
                asset_class="cash",
            )
        )
        for pos in positions:
            ac = "stock"
            if scheduler:
                for sym, asset_class in scheduler.watchlist:
                    if str(sym) == pos.symbol:
                        ac = asset_class.value
                        break
            if pos.symbol in {
                str(symbol)
                for symbol, instrument in instruments.items()
                if getattr(instrument, "asset_class", None) is not None
            }:
                instrument = instruments.get(Symbol(pos.symbol))
                if instrument is not None:
                    ac = instrument.asset_class.value
            name = pos.display_name or pos.name or pos.symbol

            allocation.append(
                AllocationItem(
                    symbol=pos.symbol,
                    name=name,
                    weight=pos.market_value / total_equity,
                    value=pos.market_value,
                    asset_class=ac,
                )
            )

    allocation_grouped = build_grouped_allocation(allocation, total_equity)

    if hasattr(portfolio, "total_deposits"):
        total_deposits = float(portfolio.total_deposits)
    elif state.db is not None:
        total_deposits = await state.db.get_total_deposits()
    else:
        total_deposits = 0.0

    return PortfolioSnapshot(
        cash=float(portfolio.cash),
        total_equity=total_equity,
        total_deposits=total_deposits,
        positions=positions,
        allocation=allocation,
        allocation_grouped=allocation_grouped,
        closed_positions=closed_positions,
        position_review_items=position_review_items,
        realized_pnl_total=realized_pnl_total,
        **valuation_identity_fields(valuation_snapshot),
    )


async def build_account_state_response(
    state,
    *,
    snapshot: PortfolioSnapshot | None = None,
) -> AccountStateResponse:
    """Project canonical Account State from one exact Portfolio snapshot."""
    resolved_snapshot = snapshot or await build_portfolio_snapshot(state)
    risks = build_risk_summary(
        resolved_snapshot,
        collect_latest_quote_timestamps(state),
    )
    projection = build_account_state_projection(resolved_snapshot, risks)
    return AccountStateResponse(
        summary=with_overview_quote_metadata(
            projection.summary,
            resolved_snapshot,
        ),
        snapshot=projection.snapshot,
        risks=projection.risks,
        next_step=projection.next_step,
    )


__all__ = (
    "adapt_persistent_quote_for_portfolio",
    "asset_class_for_position",
    "asset_class_from_config",
    "asset_class_from_ledger",
    "asset_class_from_metadata",
    "asset_class_from_watchlist",
    "broker_cost_basis_evidence_by_symbol",
    "broker_cost_basis_fields",
    "build_account_state_response",
    "build_grouped_allocation",
    "build_portfolio_snapshot",
    "can_refresh_quotes",
    "collect_latest_quote_timestamps",
    "collect_latest_quotes",
    "confirm_pending_fund_orders",
    "current_valuation_snapshot",
    "ensure_asset_config",
    "has_position_ledger_entries",
    "has_rows",
    "hydrate_missing_position_quotes",
    "is_unconfirmed_fund_estimate",
    "ledger_entry_shanghai_date",
    "ledger_entry_trade_total_fee",
    "merge_quote_identity",
    "normalize_asset_class",
    "normalize_asset_class_value",
    "optional_float_attr",
    "optional_float_value",
    "parse_fee_breakdown",
    "position_quote_presentation",
    "quote_age_seconds",
    "quote_latest_price",
    "quote_market_timestamp",
    "quote_merge_timestamp",
    "quote_source",
    "quote_stale_reason",
    "quotes_from_valuation_snapshot",
    "read_daily_ledger_entries",
    "refresh_policy",
    "resolve_fund_buy_fill",
    "resolve_live_holding_baseline",
    "resolve_position_today_change",
    "resolve_projection_sources",
    "response_quote_status",
    "same_day_buy_lots",
    "same_day_sell_lots",
    "snapshot_quote_age_seconds",
    "snapshot_quote_source",
    "snapshot_quote_status",
    "snapshot_stale_reason",
    "snapshot_uses_persistent_cache",
    "store_runtime_quote",
    "using_persistent_cache",
    "with_overview_quote_metadata",
)
