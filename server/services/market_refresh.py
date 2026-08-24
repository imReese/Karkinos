"""Application projection extracted from the HTTP delivery adapter."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime
from functools import partial
from zoneinfo import ZoneInfo

from core.types import AssetClass, Symbol
from server.contracts.http.market import (
    QuoteRefreshSymbolResult,
)
from server.services.asset_metadata import (
    resolve_asset_metadata,
)
from server.services.market_hours import is_cn_trading_session
from server.services.market_indices import (
    market_index_display_name,
)
from server.services.market_refresh_errors import (
    TUSHARE_FUND_NAV_PERMISSION_DENIED as _TUSHARE_FUND_NAV_PERMISSION_DENIED,
)
from server.services.market_refresh_errors import (
    provider_error_code,
    provider_error_reason,
)

logger = logging.getLogger(__name__)

QUOTE_REFRESH_ATTEMPTS: dict[tuple[str, str], datetime] = {}

QUOTE_REFRESH_ERRORS: dict[tuple[str, str], str | None] = {}

MANUAL_REFRESH_TIMEOUT_SECONDS = 8.0

PROVIDER_REFRESH_TIMEOUT_SECONDS = 3.0

INDEX_PROVIDER_REFRESH_TIMEOUT_SECONDS = 7.0

_BLOCKING_FETCH_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="market-fetch",
)

_SH_TZ = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    return datetime.now(_SH_TZ)


def parse_quote_timestamp(timestamp: object) -> datetime | None:
    if isinstance(timestamp, datetime):
        parsed = timestamp
    elif isinstance(timestamp, str) and timestamp.strip():
        value = timestamp.strip()
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.fromisoformat(f"{value}T00:00:00")
            except ValueError:
                return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_SH_TZ)
    return parsed.astimezone(_SH_TZ)


def quote_age_seconds(quote: dict | None, now: datetime | None = None) -> int | None:
    timestamp = parse_quote_timestamp(None if quote is None else quote.get("timestamp"))
    if timestamp is None:
        return None
    current = now or shanghai_now()
    return max(int((current - timestamp).total_seconds()), 0)


def latest_refresh_attempt(symbol: str, asset_class: str) -> str | None:
    attempt = QUOTE_REFRESH_ATTEMPTS.get((symbol, asset_class))
    return None if attempt is None else attempt.isoformat()


def latest_refresh_error(symbol: str, asset_class: str) -> str | None:
    return QUOTE_REFRESH_ERRORS.get((symbol, asset_class))


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


def is_real_persistent_quote(quote: dict | None) -> bool:
    return bool(quote and quote.get("price") not in {None, ""})


def mark_persistent_cache_quote(
    quote: dict | None, *, stale_reason: str = "source_unavailable"
) -> dict | None:
    if quote is None:
        return None
    marked = dict(quote)
    marked["quote_status"] = "stale"
    marked["stale_reason"] = stale_reason
    marked["provider_status"] = "error"
    marked["using_persistent_cache"] = True
    marked["persistent_cache_status"] = "available"
    return marked


def stale_reason(
    state,
    quote: dict | None,
    *,
    market_open: bool,
    refresh_policy: str,
    now: datetime | None = None,
) -> str | None:
    if not quote or quote.get("price") in {None, ""}:
        return (
            str(quote.get("stale_reason"))
            if quote and quote.get("stale_reason")
            else "no_real_data_available"
        )

    timestamp = parse_quote_timestamp(quote.get("timestamp"))
    if timestamp is None:
        return "quote_timestamp_missing"

    if resolve_quote_status(state, quote, now=now) != "stale":
        return None

    if refresh_policy == "cache_only":
        return (
            "market_closed_cache_only"
            if not market_open
            else "refresh_policy_cache_only"
        )

    age = quote_age_seconds(quote, now=now)
    ttl_seconds = (
        max(int(getattr(state.config, "live_poll_interval", 60) or 60), 15) * 3
    )
    if age is not None and age > ttl_seconds:
        return "quote_older_than_expected_session"

    return "quote_older_than_expected_session"


def quote_metadata(
    state,
    symbol: str,
    asset_class: str,
    quote: dict | None,
    *,
    market_open: bool,
    refresh_policy: str,
    now: datetime | None = None,
) -> dict:
    metadata = resolve_asset_metadata(
        state,
        symbol,
        asset_class=asset_class,
        quote=quote,
        fallback_name=symbol,
    )
    display_name = (
        (
            str(quote.get("display_name") or quote.get("name") or "").strip()
            if quote
            else ""
        )
        or market_index_display_name(symbol)
        or metadata.display_name
    )
    daily_change = (
        None
        if quote is None
        else optional_float(
            quote.get("daily_change")
            or quote.get("day_change_value")
            or quote.get("change")
        )
    )
    daily_change_pct = (
        None
        if quote is None
        else optional_float(
            quote.get("daily_change_pct")
            or quote.get("day_change_pct")
            or quote.get("change_pct")
            or quote.get("change_percent")
            or quote.get("pct_chg")
        )
    )
    quote_status = (
        "missing"
        if not quote or quote.get("price") in {None, ""}
        else resolve_quote_status(state, quote, now=now)
    )
    resolved_stale_reason = (
        str(quote.get("stale_reason"))
        if quote and quote.get("stale_reason")
        else stale_reason(
            state,
            quote,
            market_open=market_open,
            refresh_policy=refresh_policy,
            now=now,
        )
    )
    return {
        "name": display_name,
        "display_name": display_name,
        "daily_change": daily_change,
        "daily_change_pct": daily_change_pct,
        "change": daily_change,
        "change_pct": daily_change_pct,
        "pct_chg": daily_change_pct,
        "quote_status": quote_status,
        "quote_source": quote_source(state, quote),
        "quote_age_seconds": quote_age_seconds(quote, now=now),
        "stale_reason": resolved_stale_reason,
        "last_refresh_attempt": latest_refresh_attempt(symbol, asset_class),
        "last_refresh_error": latest_refresh_error(symbol, asset_class),
        "using_persistent_cache": bool(
            quote
            and (
                quote.get("using_persistent_cache")
                or quote.get("captured_reason") == "persistent_cache"
            )
        ),
        "nav_date": None if quote is None else quote.get("nav_date"),
    }


def latest_persistent_real_quote(state, symbol: str) -> dict | None:
    if state.db is None or not hasattr(state.db, "get_latest_quotes_sync"):
        return None
    for row in state.db.get_latest_quotes_sync():
        if row.get("symbol") == symbol and is_real_persistent_quote(row):
            return row
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


def optional_float(value) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


async def run_blocking_fetch(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _BLOCKING_FETCH_EXECUTOR,
        partial(func, *args),
    )


def upsert_instrument_metadata_from_quote(
    state,
    *,
    symbol: str,
    asset_type: str,
    snapshot: dict,
    provider_name: str | None,
    fetched_at: str | None = None,
) -> None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "upsert_instrument_metadata_sync"):
        return
    display_name = str(
        snapshot.get("display_name")
        or snapshot.get("name")
        or snapshot.get("asset_name")
        or ""
    ).strip()
    if not display_name:
        return
    try:
        db.upsert_instrument_metadata_sync(
            symbol=symbol,
            asset_type=asset_type,
            display_name=display_name,
            provider_symbol=snapshot.get("provider_symbol") or symbol,
            exchange=snapshot.get("exchange"),
            market=snapshot.get("market"),
            provider_name=provider_name,
            source="quote",
            fetched_at=fetched_at,
            metadata={
                "source": snapshot.get("source"),
                "quote_source": snapshot.get("quote_source"),
            },
        )
    except Exception:
        logger.warning(
            "Failed to upsert instrument metadata for %s", symbol, exc_info=True
        )


def upsert_latest_quote_snapshot(
    state,
    *,
    symbol: str,
    asset_type: str,
    snapshot: dict,
    quote_source: str | None,
    provider_name: str | None,
    provider_status: str | None,
    quote_status: str,
    captured_reason: str,
    nav_date: str | None = None,
    fetch_run_id: str | None = None,
) -> None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "upsert_latest_quote_sync"):
        return
    timestamp = snapshot.get("timestamp")
    if not timestamp:
        return
    try:
        db.upsert_latest_quote_sync(
            symbol=symbol,
            asset_type=asset_type,
            price=float(snapshot["price"]),
            previous_close=optional_float(snapshot.get("previous_close")),
            change=optional_float(snapshot.get("change")),
            change_percent=optional_float(
                snapshot.get("change_percent") or snapshot.get("pct_chg")
            ),
            volume=optional_float(snapshot.get("volume")),
            turnover=optional_float(snapshot.get("turnover") or snapshot.get("amount")),
            quote_timestamp=str(timestamp),
            quote_source=quote_source,
            provider_name=provider_name,
            provider_status=provider_status,
            quote_status=quote_status,
            stale_reason=snapshot.get("stale_reason"),
            captured_at=datetime.now().isoformat(),
            captured_reason=captured_reason,
            nav_date=nav_date,
            fetch_run_id=fetch_run_id,
            metadata={
                "source": snapshot.get("source"),
                "display_name": snapshot.get("display_name") or snapshot.get("name"),
            },
        )
        upsert_instrument_metadata_from_quote(
            state,
            symbol=symbol,
            asset_type=asset_type,
            snapshot=snapshot,
            provider_name=provider_name,
            fetched_at=str(timestamp),
        )
    except Exception:
        logger.warning("Failed to upsert latest quote for %s", symbol, exc_info=True)


def resolve_quote_status(
    state,
    quote: dict | None,
    *,
    now: datetime | None = None,
) -> str:
    try:
        from server.projections.quote_status import quote_status

        return quote_status(state, quote, now=now)
    except Exception:
        logger.warning("Failed to resolve quote status", exc_info=True)
        return "live" if quote and quote.get("timestamp") else "stale"


def load_latest_snapshot_from_provider(
    state, symbol: str, asset_class: AssetClass
) -> dict | None:
    from data.manager import build_sources

    data_source = getattr(state.config, "data_source", "akshare")
    tushare_token = getattr(state.config, "tushare_token", "")
    sources = build_sources(
        data_source=data_source,
        tushare_token=tushare_token,
    )
    configured_source_name = data_source if data_source in sources else "akshare"
    preferred = sources.get(configured_source_name, sources["akshare"])
    source_chain = [(configured_source_name, preferred)]
    if configured_source_name != "akshare":
        akshare = sources.get("akshare")
        if akshare is not None and akshare is not preferred:
            source_chain.append(("akshare", akshare))

    # TuShare's latest-quote adapter supports stocks and open-end funds only.
    # Route unsupported asset classes directly to the registered AKShare edge
    # source so one manual refresh does not spend its bounded time budget on a
    # provider that cannot return the requested instrument type.
    if configured_source_name == "tushare" and asset_class in {
        AssetClass.INDEX,
        AssetClass.GOLD,
        AssetClass.BOND,
    }:
        akshare = sources.get("akshare")
        source_chain = [("akshare", akshare)] if akshare is not None else []

    snapshot = None
    selected_source_name = data_source
    last_error: Exception | None = None
    fallback_reason_code: str | None = None
    primary_source_name = source_chain[0][0]
    for source_name, source in source_chain:
        try:
            snapshot = fetch_provider_latest_with_timeout(
                source,
                symbol,
                asset_class,
                timeout_seconds=(
                    INDEX_PROVIDER_REFRESH_TIMEOUT_SECONDS
                    if asset_class == AssetClass.INDEX
                    else PROVIDER_REFRESH_TIMEOUT_SECONDS
                ),
            )
            last_error = None
        except Exception as exc:
            logger.warning(
                "Latest quote provider failed: %s %s (%s)",
                source_name,
                symbol,
                asset_class.value,
                exc_info=True,
            )
            last_error = exc
            if source_name == primary_source_name:
                fallback_reason_code = provider_error_code(exc)
            snapshot = None
        if snapshot:
            selected_source_name = source_name
            break
    if not snapshot:
        if last_error is not None:
            raise last_error
        return None
    payload = {
        "symbol": symbol,
        "asset_class": asset_class.value,
        "price": snapshot["price"],
        "volume": snapshot.get("volume"),
        "timestamp": snapshot.get("timestamp"),
        "source": snapshot.get("source") or selected_source_name,
        "quote_source": snapshot.get("quote_source")
        or snapshot.get("source")
        or selected_source_name,
        "provider_name": snapshot.get("provider_name") or selected_source_name,
        "provider_symbol": snapshot.get("provider_symbol") or symbol,
        "exchange": snapshot.get("exchange"),
        "market": snapshot.get("market"),
        "quote_status": "live",
        "provider_status": (
            "fallback" if selected_source_name != configured_source_name else "live"
        ),
        "stale_reason": fallback_reason_code,
        "nav_date": snapshot.get("nav_date")
        or (snapshot.get("timestamp") if asset_class == AssetClass.FUND else None),
    }
    display_name = snapshot.get("display_name") or snapshot.get("name")
    if display_name:
        payload["display_name"] = str(display_name)
        payload["name"] = str(display_name)
    previous_close = snapshot.get("previous_close")
    previous_close_date = snapshot.get("previous_close_date")
    change = snapshot.get("change") or snapshot.get("day_change_value")
    change_percent = (
        snapshot.get("change_percent")
        or snapshot.get("pct_chg")
        or snapshot.get("day_change_pct")
    )
    payload["previous_close"] = previous_close
    payload["previous_close_date"] = previous_close_date
    payload["change"] = change
    payload["change_percent"] = change_percent
    return payload


def fetch_provider_latest_with_timeout(
    source,
    symbol: str,
    asset_class: AssetClass,
    *,
    timeout_seconds: float,
) -> dict | None:
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quote-provider")
    future = executor.submit(source.fetch_latest, Symbol(symbol), asset_class)
    try:
        return future.result(timeout=max(float(timeout_seconds), 0.001))
    except FutureTimeoutError as exc:
        future.cancel()
        raise TimeoutError(
            f"provider fetch_latest timed out after {timeout_seconds:.1f}s"
        ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def persist_latest_snapshot(
    state,
    symbol: str,
    payload: dict,
    *,
    fetch_run_id: str | None = None,
) -> None:
    if (
        state.db is not None
        and hasattr(state.db, "save_quote_snapshot_sync")
        and payload.get("timestamp")
    ):
        captured_reason = "manual_or_route_refresh"
        state.db.save_quote_snapshot_sync(
            symbol=symbol,
            asset_class=payload["asset_class"],
            price=float(payload["price"]),
            volume=None if payload["volume"] is None else float(payload["volume"]),
            timestamp=str(payload["timestamp"]),
            quote_source=payload["quote_source"],
            provider_name=payload["provider_name"],
            quote_status=payload["quote_status"],
            provider_status=payload["provider_status"],
            captured_reason=captured_reason,
            nav_date=payload.get("nav_date"),
            fetch_run_id=fetch_run_id,
        )
        snapshot_metadata = dict(payload)
        upsert_latest_quote_snapshot(
            state,
            symbol=symbol,
            asset_type=payload["asset_class"],
            snapshot=snapshot_metadata,
            quote_source=payload["quote_source"],
            provider_name=payload["provider_name"],
            provider_status=payload["provider_status"],
            quote_status=payload["quote_status"],
            captured_reason=captured_reason,
            nav_date=payload.get("nav_date"),
            fetch_run_id=fetch_run_id,
        )
        previous_close = payload.get("previous_close")
        previous_close_date = payload.get("previous_close_date")
        if (
            previous_close not in {None, ""}
            and previous_close_date not in {None, ""}
            and hasattr(state.db, "save_daily_close_snapshot_sync")
        ):
            state.db.save_daily_close_snapshot_sync(
                symbol=symbol,
                asset_class=payload["asset_class"],
                trade_date=str(previous_close_date),
                close_price=float(previous_close),
                source="reported_previous_close",
            )


def fetch_latest_snapshot(state, symbol: str, asset_class: AssetClass) -> dict | None:
    payload = load_latest_snapshot_from_provider(state, symbol, asset_class)
    if payload:
        persist_latest_snapshot(state, symbol, payload)
    return payload


async def refresh_one_quote(
    state,
    symbol: str,
    asset_class: AssetClass,
    timeout_seconds: float | None = None,
    fetch_run_id: str | None = None,
) -> QuoteRefreshSymbolResult:
    timeout = (
        MANUAL_REFRESH_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    )
    key = (symbol, asset_class.value)
    attempted_at = datetime.now()
    QUOTE_REFRESH_ATTEMPTS[key] = attempted_at
    QUOTE_REFRESH_ERRORS[key] = None
    market_open = is_cn_trading_session()
    refresh_policy = "live" if market_open else "cache_only"
    try:
        snapshot = await asyncio.wait_for(
            run_blocking_fetch(
                load_latest_snapshot_from_provider,
                state,
                symbol,
                asset_class,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        cached_quote = latest_persistent_real_quote(state, symbol)
        cached_quote = mark_persistent_cache_quote(
            cached_quote, stale_reason="provider_timeout"
        )
        QUOTE_REFRESH_ERRORS[key] = "provider_timeout"
        metadata = quote_metadata(
            state,
            symbol,
            asset_class.value,
            cached_quote,
            market_open=market_open,
            refresh_policy=refresh_policy,
        )
        return QuoteRefreshSymbolResult(
            symbol=symbol,
            asset_class=asset_class.value,
            status="failed",
            quote_timestamp=(
                None if cached_quote is None else cached_quote.get("timestamp")
            ),
            quote_source=metadata["quote_source"],
            quote_age_seconds=metadata["quote_age_seconds"],
            error="provider_timeout",
            reason=(
                "行情源刷新超时，继续使用本地缓存"
                if cached_quote
                else "行情源刷新超时，暂无真实行情数据"
            ),
            last_refresh_attempt=attempted_at.isoformat(),
            last_refresh_error="provider_timeout",
            using_persistent_cache=bool(cached_quote),
        )
    except Exception as exc:
        cached_quote = latest_persistent_real_quote(state, symbol)
        logger.warning("Manual quote refresh failed for %s", symbol, exc_info=True)
        error_code = provider_error_code(exc)
        error_message = error_code or str(exc)
        QUOTE_REFRESH_ERRORS[key] = error_message
        cached_quote = mark_persistent_cache_quote(
            cached_quote, stale_reason=error_code or "provider_unavailable"
        )
        metadata = quote_metadata(
            state,
            symbol,
            asset_class.value,
            cached_quote,
            market_open=market_open,
            refresh_policy=refresh_policy,
        )
        return QuoteRefreshSymbolResult(
            symbol=symbol,
            asset_class=asset_class.value,
            status="failed",
            quote_timestamp=(
                None if cached_quote is None else cached_quote.get("timestamp")
            ),
            quote_source=metadata["quote_source"],
            quote_age_seconds=metadata["quote_age_seconds"],
            error=error_message,
            reason=provider_error_reason(
                error_message,
                using_cache=bool(cached_quote),
            ),
            last_refresh_attempt=attempted_at.isoformat(),
            last_refresh_error=error_message,
            using_persistent_cache=bool(cached_quote),
        )

    if not snapshot:
        cached_quote = latest_persistent_real_quote(state, symbol)
        cached_quote = mark_persistent_cache_quote(
            cached_quote, stale_reason="source_unavailable"
        )
        error_message = None if cached_quote else "no_real_data_available"
        QUOTE_REFRESH_ERRORS[key] = error_message
        metadata = quote_metadata(
            state,
            symbol,
            asset_class.value,
            cached_quote,
            market_open=market_open,
            refresh_policy=refresh_policy,
        )
        return QuoteRefreshSymbolResult(
            symbol=symbol,
            asset_class=asset_class.value,
            status="stale" if cached_quote else "failed",
            quote_timestamp=(
                None if cached_quote is None else cached_quote.get("timestamp")
            ),
            quote_source=metadata["quote_source"],
            quote_age_seconds=metadata["quote_age_seconds"],
            error=error_message,
            reason=(
                "行情源没有返回新报价，继续使用本地缓存"
                if cached_quote
                else "暂无真实行情数据，请配置数据源或执行首次同步"
            ),
            last_refresh_attempt=attempted_at.isoformat(),
            last_refresh_error=error_message,
            using_persistent_cache=bool(cached_quote),
        )

    try:
        persist_latest_snapshot(
            state,
            symbol,
            snapshot,
            fetch_run_id=fetch_run_id,
        )
    except Exception:
        logger.exception("Failed to persist refreshed quote for %s", symbol)
        error_message = "quote_persistence_failed"
        QUOTE_REFRESH_ERRORS[key] = error_message
        return QuoteRefreshSymbolResult(
            symbol=symbol,
            asset_class=asset_class.value,
            status="failed",
            quote_timestamp=snapshot.get("timestamp"),
            quote_source=snapshot.get("quote_source"),
            error=error_message,
            reason="行情已获取但未完整落库，拒绝发布为可用行情",
            last_refresh_attempt=attempted_at.isoformat(),
            last_refresh_error=error_message,
            using_persistent_cache=bool(latest_persistent_real_quote(state, symbol)),
        )
    store_runtime_quote(state, symbol, snapshot)
    quote_status = resolve_quote_status(state, snapshot)
    metadata = quote_metadata(
        state,
        symbol,
        asset_class.value,
        snapshot,
        market_open=market_open,
        refresh_policy=refresh_policy,
    )
    return QuoteRefreshSymbolResult(
        symbol=symbol,
        asset_class=asset_class.value,
        status="refreshed" if quote_status == "live" else "stale",
        quote_timestamp=snapshot.get("timestamp"),
        quote_source=metadata["quote_source"],
        quote_age_seconds=metadata["quote_age_seconds"],
        reason=None if quote_status == "live" else "行情源返回的报价仍为缓存行情",
        last_refresh_attempt=attempted_at.isoformat(),
        last_refresh_error=None,
        using_persistent_cache=False,
    )


__all__ = (
    "fetch_latest_snapshot",
    "fetch_provider_latest_with_timeout",
    "is_real_persistent_quote",
    "latest_persistent_real_quote",
    "latest_refresh_attempt",
    "latest_refresh_error",
    "load_latest_snapshot_from_provider",
    "mark_persistent_cache_quote",
    "optional_float",
    "parse_quote_timestamp",
    "persist_latest_snapshot",
    "provider_error_code",
    "provider_error_reason",
    "quote_age_seconds",
    "quote_metadata",
    "quote_source",
    "refresh_one_quote",
    "resolve_quote_status",
    "run_blocking_fetch",
    "shanghai_now",
    "stale_reason",
    "store_runtime_quote",
    "upsert_instrument_metadata_from_quote",
    "upsert_latest_quote_snapshot",
)
