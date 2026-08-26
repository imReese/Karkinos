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
from server.services.market_quote_ingestion import (
    build_quote_ingestion_command,
    persist_quote_ingestion,
)
from server.services.market_refresh_errors import (
    TUSHARE_FUND_NAV_PERMISSION_DENIED as _TUSHARE_FUND_NAV_PERMISSION_DENIED,
)
from server.services.market_refresh_errors import (
    provider_error_code,
    provider_error_reason,
)
from server.services.market_refresh_provider import load_provider_quote_payload

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
    publish = getattr(scheduler, "publish_runtime_quote", None)
    if not callable(publish):
        return
    publish(symbol, quote)


def publish_committed_runtime_quotes(state, results) -> None:
    """Expose only quotes from a database batch that has been published."""

    database = getattr(state, "db", None)
    if database is None or not hasattr(database, "get_latest_quote_sync"):
        raise RuntimeError("published quote database is unavailable")
    for result in results:
        row = database.get_latest_quote_sync(result.symbol, result.asset_class)
        if not isinstance(row, dict) or row.get("fetch_run_id") is None:
            raise RuntimeError(f"published quote missing for {result.symbol}")
        quote = {
            **row,
            "timestamp": row.get("quote_timestamp"),
            "asset_class": row.get("asset_type") or result.asset_class,
        }
        store_runtime_quote(state, result.symbol, quote)


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
    return load_provider_quote_payload(
        state,
        symbol,
        asset_class,
        fetch_with_timeout=fetch_provider_latest_with_timeout,
        provider_timeout_seconds=PROVIDER_REFRESH_TIMEOUT_SECONDS,
        index_timeout_seconds=INDEX_PROVIDER_REFRESH_TIMEOUT_SECONDS,
    )


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
    database = getattr(state, "db", None)
    if database is None:
        raise RuntimeError("quote persistence database is unavailable")
    command = build_quote_ingestion_command(
        symbol=symbol,
        asset_type=str(payload["asset_class"]),
        snapshot=payload,
        quote_source=str(payload.get("quote_source") or "") or None,
        provider_name=str(payload.get("provider_name") or "") or None,
        provider_status=str(payload.get("provider_status") or "") or None,
        quote_status=str(payload.get("quote_status") or "live"),
        captured_reason="manual_or_route_refresh",
        nav_date=(str(payload.get("nav_date")) if payload.get("nav_date") else None),
        fetch_run_id=fetch_run_id,
    )
    persist_quote_ingestion(database, command)


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
    if fetch_run_id is None:
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
    "publish_committed_runtime_quotes",
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
)
