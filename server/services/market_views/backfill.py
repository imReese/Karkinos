"""Canonical market backfill projections."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from core.types import AssetClass, BarFrequency, Symbol
from server.contracts.http.market import (
    InstrumentMetadataBackfillItem,
    InstrumentMetadataBackfillRequest,
    InstrumentMetadataBackfillResponse,
    MarketBarsBackfillItem,
    MarketBarsBackfillRequest,
    MarketBarsBackfillResponse,
)
from server.services.market_refresh import run_blocking_fetch as _run_blocking_fetch
from server.services.market_refresh import shanghai_now as _shanghai_now
from server.services.market_views.health_inputs import (
    merged_watchlist_assets,
    normalize_asset_class,
    normalize_refresh_symbols,
)

logger = logging.getLogger(__name__)

_BAR_BACKFILL_TIMEOUT_SECONDS = 60.0

_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
    "index": AssetClass.INDEX,
}


def metadata_name_is_useful(row: dict | None, symbol: str) -> bool:
    if not row:
        return False
    display_name = str(row.get("display_name") or "").strip()
    return bool(
        display_name and display_name != symbol and display_name != f"{symbol} A股"
    )


def instrument_metadata_targets(
    state,
    requested_symbols: list[str] | None = None,
) -> list[dict[str, str]]:
    by_symbol: dict[str, dict[str, str]] = {}
    for asset_cfg in merged_watchlist_assets(state):
        symbol = str(asset_cfg.get("symbol") or "").strip()
        if not symbol:
            continue
        by_symbol.setdefault(
            symbol,
            {
                "symbol": symbol,
                "asset_class": normalize_asset_class(asset_cfg.get("asset_class")),
            },
        )

    symbols = normalize_refresh_symbols(requested_symbols)
    if symbols:
        return [
            by_symbol.get(
                symbol,
                {
                    "symbol": symbol,
                    "asset_class": AssetClass.STOCK.value,
                },
            )
            for symbol in symbols
        ]
    return list(by_symbol.values())


def provider_asset_class(asset_class: str) -> AssetClass:
    return _ASSET_CLASS_MAP.get(asset_class, AssetClass.STOCK)


def bar_frequency(interval: str) -> BarFrequency:
    frequency = {
        "1m": BarFrequency.MIN_1,
        "5m": BarFrequency.MIN_5,
        "1d": BarFrequency.DAILY,
    }.get(interval)
    if frequency is None:
        raise HTTPException(
            status_code=422, detail="interval must be one of 1d, 1m, 5m"
        )
    return frequency


def parse_backfill_date(
    value: str | None, *, field_name: str, default: date
) -> datetime:
    raw = value or default.isoformat()
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must use YYYY-MM-DD",
        ) from exc


def market_bar_backfill_range(
    state, request: MarketBarsBackfillRequest
) -> tuple[datetime, datetime]:
    config_start = getattr(state.config, "start_date", None)
    default_start = date.today() - timedelta(days=365)
    if config_start:
        try:
            default_start = date.fromisoformat(str(config_start))
        except ValueError:
            pass
    start = parse_backfill_date(
        request.start, field_name="start", default=default_start
    )
    end = parse_backfill_date(
        request.end,
        field_name="end",
        default=_shanghai_now().date(),
    )
    if start > end:
        raise HTTPException(
            status_code=422, detail="start must be before or equal to end"
        )
    return start, end


def market_bar_backfill_targets(
    state,
    request: MarketBarsBackfillRequest,
) -> list[dict[str, str]]:
    targets = instrument_metadata_targets(state, request.symbols)
    if request.asset_class:
        asset_class = normalize_asset_class(request.asset_class)
        targets = [{**target, "asset_class": asset_class} for target in targets]
    return targets


def meta_covers_range(meta: dict | None, start: datetime, end: datetime) -> bool:
    if not meta or not meta.get("start_date") or not meta.get("end_date"):
        return False
    try:
        meta_start = datetime.fromisoformat(str(meta["start_date"]))
        meta_end = datetime.fromisoformat(str(meta["end_date"]))
    except ValueError:
        return False
    return meta_start <= start and meta_end >= end


async def backfill_market_bars(
    state,
    request: MarketBarsBackfillRequest,
) -> MarketBarsBackfillResponse:
    from data.manager import DataManager, build_sources
    from data.store import DataStore

    provider_name = str(getattr(state.config, "data_source", "akshare") or "akshare")
    frequency = bar_frequency(request.interval)
    start, end = market_bar_backfill_range(state, request)
    targets = market_bar_backfill_targets(state, request)
    store = DataStore()
    manager = DataManager(
        sources=build_sources(
            data_source=provider_name,
            tushare_token=getattr(state.config, "tushare_token", ""),
        ),
        store=store,
        default_source=provider_name,
    )

    def _run_backfill() -> list[MarketBarsBackfillItem]:
        items: list[MarketBarsBackfillItem] = []
        for target in targets:
            symbol = target["symbol"]
            asset_class = normalize_asset_class(target.get("asset_class"))
            resolved_provider_asset_class = provider_asset_class(asset_class)
            before = store.get_meta(Symbol(symbol), frequency)
            cached_before = meta_covers_range(before, start, end)
            try:
                handler = manager.get_bars(
                    Symbol(symbol),
                    start,
                    end,
                    frequency,
                    resolved_provider_asset_class,
                    allow_remote_refresh=True,
                    refresh_ttl_seconds=0 if request.force else None,
                    degrade_to_cache=False,
                )
                after = store.get_meta(Symbol(symbol), frequency)
                status = "cached" if cached_before and not request.force else "updated"
                items.append(
                    MarketBarsBackfillItem(
                        symbol=symbol,
                        asset_class=asset_class,
                        status=status,
                        row_count=int(getattr(handler, "total_bars", 0)),
                        stored_start=None if after is None else after.get("start_date"),
                        stored_end=None if after is None else after.get("end_date"),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Historical bar backfill failed for %s",
                    symbol,
                    exc_info=True,
                )
                items.append(
                    MarketBarsBackfillItem(
                        symbol=symbol,
                        asset_class=asset_class,
                        status="failed",
                        error=str(exc),
                    )
                )
        return items

    items = await asyncio.wait_for(
        _run_blocking_fetch(_run_backfill),
        timeout=_BAR_BACKFILL_TIMEOUT_SECONDS,
    )
    return MarketBarsBackfillResponse(
        provider=provider_name,
        interval=frequency.value,
        start=start.date().isoformat(),
        end=end.date().isoformat(),
        requested_count=len(targets),
        updated_count=sum(1 for item in items if item.status == "updated"),
        cached_count=sum(1 for item in items if item.status == "cached"),
        failed_count=sum(1 for item in items if item.status == "failed"),
        items=items,
    )


def extract_provider_display_name(payload: dict | None) -> str | None:
    if not payload:
        return None
    display_name = str(
        payload.get("display_name")
        or payload.get("name")
        or payload.get("asset_name")
        or ""
    ).strip()
    return display_name or None


async def backfill_instrument_metadata(
    state,
    request: InstrumentMetadataBackfillRequest,
) -> InstrumentMetadataBackfillResponse:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "upsert_instrument_metadata_sync"):
        raise HTTPException(
            status_code=503, detail="instrument metadata database is unavailable"
        )

    from data.manager import build_sources

    provider_name = "akshare"
    sources = build_sources(
        data_source=getattr(state.config, "data_source", provider_name),
        tushare_token=getattr(state.config, "tushare_token", ""),
    )
    source = sources.get(provider_name)
    if source is None or not hasattr(source, "fetch_latest"):
        raise HTTPException(status_code=503, detail="akshare source is unavailable")

    items: list[InstrumentMetadataBackfillItem] = []
    timeout = float(
        getattr(state.config, "metadata_backfill_timeout_seconds", 8.0) or 8.0
    )

    for target in instrument_metadata_targets(state, request.symbols):
        symbol = target["symbol"]
        asset_class = target["asset_class"]
        existing = (
            db.get_instrument_metadata_sync(symbol, asset_class)
            if hasattr(db, "get_instrument_metadata_sync")
            else None
        )
        if metadata_name_is_useful(existing, symbol) and not request.force:
            items.append(
                InstrumentMetadataBackfillItem(
                    symbol=symbol,
                    asset_class=asset_class,
                    status="skipped",
                    display_name=existing.get("display_name"),
                    provider=existing.get("provider_name") or existing.get("provider"),
                )
            )
            continue

        try:
            payload = await asyncio.wait_for(
                _run_blocking_fetch(
                    source.fetch_latest,
                    Symbol(symbol),
                    provider_asset_class(asset_class),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            items.append(
                InstrumentMetadataBackfillItem(
                    symbol=symbol,
                    asset_class=asset_class,
                    status="failed",
                    provider=provider_name,
                    error="provider_timeout",
                )
            )
            continue
        except Exception as exc:
            logger.warning(
                "Instrument metadata backfill failed for %s", symbol, exc_info=True
            )
            items.append(
                InstrumentMetadataBackfillItem(
                    symbol=symbol,
                    asset_class=asset_class,
                    status="failed",
                    provider=provider_name,
                    error=str(exc),
                )
            )
            continue

        display_name = extract_provider_display_name(payload)
        if not display_name:
            items.append(
                InstrumentMetadataBackfillItem(
                    symbol=symbol,
                    asset_class=asset_class,
                    status="failed",
                    provider=provider_name,
                    error="metadata_not_available",
                )
            )
            continue

        fetched_at = datetime.now().isoformat()
        db.upsert_instrument_metadata_sync(
            symbol=symbol,
            asset_type=asset_class,
            display_name=display_name,
            provider_symbol=str(payload.get("provider_symbol") or symbol),
            exchange=payload.get("exchange"),
            market=payload.get("market"),
            provider_name=provider_name,
            source="backfill",
            fetched_at=fetched_at,
            metadata={
                "quote_timestamp": payload.get("timestamp"),
                "quote_source": payload.get("quote_source")
                or payload.get("source")
                or provider_name,
                "payload_keys": sorted(str(key) for key in payload.keys()),
            },
        )
        items.append(
            InstrumentMetadataBackfillItem(
                symbol=symbol,
                asset_class=asset_class,
                status="updated",
                display_name=display_name,
                provider=provider_name,
            )
        )

    return InstrumentMetadataBackfillResponse(
        provider=provider_name,
        requested_count=len(items),
        updated_count=sum(1 for item in items if item.status == "updated"),
        skipped_count=sum(1 for item in items if item.status == "skipped"),
        failed_count=sum(1 for item in items if item.status == "failed"),
        items=items,
    )


__all__ = (
    "backfill_instrument_metadata",
    "backfill_market_bars",
    "bar_frequency",
    "extract_provider_display_name",
    "instrument_metadata_targets",
    "market_bar_backfill_range",
    "market_bar_backfill_targets",
    "meta_covers_range",
    "metadata_name_is_useful",
    "parse_backfill_date",
    "provider_asset_class",
)
