"""Provider selection and payload normalization for quote refresh commands."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from core.types import AssetClass, Symbol
from data.source_policy import MarketDataUseCase
from data.source_routing import legacy_sources_for_use_case
from server.services.market_refresh_errors import provider_error_code

logger = logging.getLogger(__name__)


def _quote_sources(*, config, use_case: MarketDataUseCase):
    """Resolve quote adapters for one source-policy use case."""
    return legacy_sources_for_use_case(config, use_case)


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


def load_provider_quote_payload(
    state,
    symbol: str,
    asset_class: AssetClass,
    *,
    fetch_with_timeout: Callable[..., dict | None],
    provider_timeout_seconds: float,
    index_timeout_seconds: float,
) -> dict | None:
    """Fetch one quote through the configured bounded provider chain."""

    use_case = {
        AssetClass.INDEX: MarketDataUseCase.INDEX_BARS,
        AssetClass.GOLD: MarketDataUseCase.GOLD_BARS,
        AssetClass.BOND: MarketDataUseCase.BOND_BARS,
        AssetClass.FUND: MarketDataUseCase.FUND_NAV,
    }.get(asset_class, MarketDataUseCase.REALTIME_QUOTES)
    sources = _quote_sources(config=state.config, use_case=use_case)
    source_chain = list(sources.items())
    legacy_configured_source = (
        None
        if getattr(state.config, "market_data_source_policy", None)
        else str(getattr(state.config, "data_source", "") or "").strip().lower() or None
    )
    configured_source_name = legacy_configured_source or source_chain[0][0]

    snapshot = None
    selected_source_name = configured_source_name
    last_error: Exception | None = None
    fallback_reason_code: str | None = None
    primary_source_name = source_chain[0][0]
    for source_name, source in source_chain:
        try:
            snapshot = fetch_with_timeout(
                source,
                symbol,
                asset_class,
                timeout_seconds=(
                    index_timeout_seconds
                    if asset_class == AssetClass.INDEX
                    else provider_timeout_seconds
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
    payload["previous_close"] = snapshot.get("previous_close")
    payload["previous_close_date"] = snapshot.get("previous_close_date")
    payload["change"] = snapshot.get("change") or snapshot.get("day_change_value")
    payload["change_percent"] = (
        snapshot.get("change_percent")
        or snapshot.get("pct_chg")
        or snapshot.get("day_change_pct")
    )
    return payload


__all__ = ("fetch_provider_latest_with_timeout", "load_provider_quote_payload")
