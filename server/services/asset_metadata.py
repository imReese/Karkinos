"""Asset identity helpers shared by portfolio and market routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.types import Symbol


@dataclass(frozen=True)
class AssetMetadata:
    symbol: str
    display_name: str
    asset_class: str
    market: str | None = None
    provider: str | None = None
    provider_symbol: str | None = None
    source: str = "fallback"


def _normalize_asset_class(value: Any) -> str:
    if value is None:
        return "other"
    normalized = getattr(value, "value", value)
    normalized = str(normalized).strip().lower()
    if normalized in {"stock", "fund", "etf", "gold", "bond", "cash"}:
        return normalized
    return "other"


def _asset_symbols(asset_cfg: dict[str, Any]) -> set[str]:
    values = {
        asset_cfg.get("symbol"),
        asset_cfg.get("provider_symbol"),
        asset_cfg.get("provider_code"),
        asset_cfg.get("code"),
    }
    aliases = asset_cfg.get("aliases") or []
    if isinstance(aliases, str):
        values.add(aliases)
    elif isinstance(aliases, (list, tuple, set)):
        values.update(aliases)
    return {str(value).strip() for value in values if str(value or "").strip()}


def _coerce_asset_config(
    symbol: str | None,
    raw: Any,
    *,
    source: str,
) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        clean_symbol = str(symbol or "").strip()
        clean_name = raw.strip()
        if not clean_symbol and not clean_name:
            return None
        return {
            "symbol": clean_symbol or clean_name,
            "display_name": clean_name or clean_symbol,
            "source": source,
        }
    if not isinstance(raw, dict):
        return None

    cfg = dict(raw)
    if symbol and not cfg.get("symbol"):
        cfg["symbol"] = str(symbol).strip()
    if cfg.get("name") and not cfg.get("display_name"):
        cfg["display_name"] = cfg.get("name")
    if cfg.get("code") and not cfg.get("provider_symbol"):
        cfg["provider_symbol"] = cfg.get("provider_code") or cfg.get("code")
    if cfg.get("provider_code") and not cfg.get("provider_symbol"):
        cfg["provider_symbol"] = cfg.get("provider_code")
    cfg["source"] = source
    if not _asset_symbols(cfg):
        return None
    return cfg


def iter_configured_asset_metadata(state: Any) -> list[dict[str, Any]]:
    """Return normalized asset identity entries from supported config shapes."""
    config = getattr(state, "config", None)
    entries: list[dict[str, Any]] = []
    for field_name in ("instruments", "assets"):
        raw_collection = getattr(config, field_name, None)
        if raw_collection is None:
            continue
        if isinstance(raw_collection, dict):
            iterable = raw_collection.items()
        else:
            iterable = enumerate(raw_collection)
        for key, raw in iterable:
            symbol = None if isinstance(key, int) else str(key)
            cfg = _coerce_asset_config(symbol, raw, source=field_name)
            if cfg is not None:
                entries.append(cfg)
    return entries


def _has_display_metadata(asset_cfg: dict[str, Any]) -> bool:
    return any(
        str(asset_cfg.get(key) or "").strip()
        for key in (
            "display_name",
            "name",
            "provider_symbol",
            "provider_code",
            "provider",
            "code",
        )
    )


def metadata_configured_count(state: Any) -> int:
    """Count configured asset identities that carry useful display metadata."""
    return sum(
        1 for asset_cfg in iter_configured_asset_metadata(state) if _has_display_metadata(asset_cfg)
    )


def _metadata_from_config(
    state: Any,
    symbol: str,
    asset_class: str,
) -> AssetMetadata | None:
    for asset_cfg in iter_configured_asset_metadata(state):
        if symbol not in _asset_symbols(asset_cfg):
            continue
        display_name = str(
            asset_cfg.get("display_name")
            or asset_cfg.get("name")
            or asset_cfg.get("symbol")
            or symbol
        )
        return AssetMetadata(
            symbol=symbol,
            display_name=display_name,
            asset_class=_normalize_asset_class(asset_cfg.get("asset_class"))
            or asset_class,
            market=asset_cfg.get("market"),
            provider=asset_cfg.get("provider"),
            provider_symbol=asset_cfg.get("provider_symbol")
            or asset_cfg.get("provider_code")
            or asset_cfg.get("code"),
            source="config",
        )
    return None


def _watchlist_symbols(state: Any) -> set[tuple[str, str | None]]:
    scheduler = getattr(state, "scheduler", None)
    symbols: set[tuple[str, str | None]] = set()
    for item in getattr(scheduler, "watchlist", []) or []:
        if isinstance(item, (list, tuple)) and item:
            symbol = str(item[0])
            asset_class = item[1] if len(item) > 1 else None
            symbols.add((symbol, _normalize_asset_class(asset_class)))
    return symbols


def _position_symbols(state: Any) -> set[tuple[str, str | None]]:
    scheduler = getattr(state, "scheduler", None)
    portfolio = getattr(scheduler, "portfolio", None)
    positions = getattr(portfolio, "positions", {}) or {}
    symbols: set[tuple[str, str | None]] = set()
    for symbol in positions:
        symbols.add((str(symbol), None))
    return symbols


def _quote_symbols(state: Any) -> set[tuple[str, str | None]]:
    scheduler = getattr(state, "scheduler", None)
    symbols: set[tuple[str, str | None]] = set()
    for symbol, quote in (getattr(scheduler, "latest_quotes", {}) or {}).items():
        asset_class = quote.get("asset_class") if isinstance(quote, dict) else None
        symbols.add((str(symbol), _normalize_asset_class(asset_class)))
    db = getattr(state, "db", None)
    get_latest_quotes = getattr(db, "get_latest_quotes_sync", None)
    if callable(get_latest_quotes):
        try:
            for quote in get_latest_quotes() or []:
                if not isinstance(quote, dict):
                    continue
                symbol = str(quote.get("symbol") or "").strip()
                if symbol:
                    symbols.add((symbol, _normalize_asset_class(quote.get("asset_class"))))
        except Exception:
            pass
    return symbols


def build_asset_metadata_status(state: Any) -> dict[str, Any]:
    """Summarize configured and missing asset identities for Settings."""
    configured_entries = iter_configured_asset_metadata(state)
    configured_assets: list[dict[str, Any]] = []
    configured_symbols: set[str] = set()
    for cfg in configured_entries:
        symbols = _asset_symbols(cfg)
        configured_symbols.update(symbols)
        primary_symbol = str(cfg.get("symbol") or next(iter(symbols), "")).strip()
        if not primary_symbol:
            continue
        configured_assets.append(
            {
                "symbol": primary_symbol,
                "display_name": str(
                    cfg.get("display_name") or cfg.get("name") or primary_symbol
                ),
                "asset_class": _normalize_asset_class(cfg.get("asset_class")),
                "provider_symbol": cfg.get("provider_symbol")
                or cfg.get("provider_code")
                or cfg.get("code"),
                "aliases": sorted(symbols - {primary_symbol}),
                "source": cfg.get("source") or "config",
            }
        )

    observed = _position_symbols(state) | _watchlist_symbols(state) | _quote_symbols(state)
    missing_symbols = sorted(
        symbol
        for symbol, _asset_class in observed
        if symbol and symbol not in configured_symbols
    )
    suggested_assets = [
        {
            "symbol": symbol,
            "asset_class": next(
                (
                    asset_class
                    for candidate, asset_class in observed
                    if candidate == symbol and asset_class
                ),
                "fund",
            ),
            "display_name": "<填入资产名称>",
            "provider_symbol": symbol,
            "aliases": [symbol],
        }
        for symbol in missing_symbols
    ]
    return {
        "configured_count": metadata_configured_count(state),
        "configured_assets": configured_assets,
        "missing_symbols": missing_symbols,
        "suggested_config": {"assets": suggested_assets},
        "metadata_source": "config",
        "has_missing_metadata": bool(missing_symbols),
    }


def _metadata_from_instrument(
    state: Any,
    symbol: str,
    asset_class: str,
) -> AssetMetadata | None:
    scheduler = getattr(state, "scheduler", None)
    instruments = getattr(scheduler, "instruments", {}) if scheduler else {}
    instrument = instruments.get(Symbol(symbol)) or instruments.get(symbol)
    if instrument is None:
        return None
    name = str(getattr(instrument, "name", "") or "").strip()
    if not name:
        return None
    return AssetMetadata(
        symbol=symbol,
        display_name=name,
        asset_class=_normalize_asset_class(
            getattr(getattr(instrument, "asset_class", None), "value", None)
        )
        or asset_class,
        source="instrument",
    )


def _metadata_from_quote(
    symbol: str,
    asset_class: str,
    quote: dict[str, Any] | None,
) -> AssetMetadata | None:
    if not quote:
        return None
    display_name = str(
        quote.get("display_name") or quote.get("name") or quote.get("asset_name") or ""
    ).strip()
    if not display_name:
        return None
    return AssetMetadata(
        symbol=symbol,
        display_name=display_name,
        asset_class=_normalize_asset_class(quote.get("asset_class")) or asset_class,
        market=quote.get("market"),
        provider=quote.get("provider") or quote.get("source"),
        provider_symbol=quote.get("provider_symbol"),
        source="quote",
    )


def resolve_asset_metadata(
    state: Any,
    symbol: str,
    *,
    asset_class: str | None = None,
    quote: dict[str, Any] | None = None,
    fallback_name: str | None = None,
) -> AssetMetadata:
    """Resolve a stable display identity without hardcoding UI names."""
    normalized_asset_class = _normalize_asset_class(asset_class)
    for candidate in (
        _metadata_from_config(state, symbol, normalized_asset_class),
        _metadata_from_quote(symbol, normalized_asset_class, quote),
        _metadata_from_instrument(state, symbol, normalized_asset_class),
    ):
        if candidate is not None:
            return candidate
    return AssetMetadata(
        symbol=symbol,
        display_name=fallback_name or symbol,
        asset_class=normalized_asset_class,
        source="fallback",
    )
