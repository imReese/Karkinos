"""Asset identity helpers shared by portfolio and market routes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from core.types import AssetClass, InstrumentType, Symbol


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
    normalized = str(normalized).strip().lower().replace("-", "_")
    if normalized in {"open_end_fund", "openend_fund"}:
        return "fund"
    if normalized in {"stock", "fund", "etf", "gold", "bond", "cash", "index"}:
        return normalized
    return "other"


def _metadata_instrument_type(row: dict[str, Any]) -> InstrumentType | None:
    raw = row.get("instrument_type") or row.get("asset_type")
    if raw is None:
        raw = row.get("asset_class")
        # An asset class alone cannot distinguish ETF from open-end fund.
        if str(getattr(raw, "value", raw) or "").strip().lower() == "fund":
            return None
    if raw is None:
        return None
    try:
        return InstrumentType.from_persisted(raw)
    except ValueError:
        return InstrumentType.UNKNOWN


def _asset_group(value: Any) -> str:
    asset_class = _normalize_asset_class(value)
    return "fund" if asset_class == "etf" else asset_class


def _matching_metadata_row(
    rows: list[dict[str, Any]],
    asset_class: str,
    instrument_type: InstrumentType | None,
    *,
    allow_legacy_names: bool = False,
) -> dict[str, Any] | None:
    if instrument_type is InstrumentType.UNKNOWN:
        return None
    requested_group = _asset_group(asset_class)
    candidates = []
    for row in rows:
        kind = _metadata_instrument_type(row)
        row_group = _asset_group(
            row.get("asset_class")
            or row.get("asset_type")
            or (kind.value if kind is not None else None)
        )
        candidates.append((kind, row_group, row))
    # Legacy config labels may fill a name only when no declared identity conflicts.
    allow_untyped = allow_legacy_names and all(
        kind is not InstrumentType.UNKNOWN
        and (instrument_type is None or kind is None or kind is instrument_type)
        and (requested_group == "other" or row_group in {"other", requested_group})
        for kind, row_group, _ in candidates
    )
    matches = []
    for kind, row_group, row in candidates:
        if kind is InstrumentType.UNKNOWN:
            continue
        if kind is not None:
            kind_group = _asset_group(kind.value)
            if row_group != "other" and row_group != kind_group:
                continue
        legacy_name = allow_untyped and kind is None
        if (
            instrument_type is not None
            and kind is not instrument_type
            and not legacy_name
        ):
            continue
        if (
            requested_group != "other"
            and row_group != requested_group
            and not (legacy_name and row_group == "other")
        ):
            continue
        matches.append((kind, row))
    if instrument_type is not None:
        exact_matches = [row for kind, row in matches if kind is instrument_type]
        if exact_matches:
            return exact_matches[0]
        if allow_untyped:
            return matches[0][1] if len(matches) == 1 else None
    if not matches or len({kind for kind, _ in matches}) > 1:
        return None
    return matches[0][1]


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
        iterable: Any = (
            raw_collection.items()
            if isinstance(raw_collection, dict)
            else enumerate(raw_collection)
        )
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
        1
        for asset_cfg in iter_configured_asset_metadata(state)
        if _has_display_metadata(asset_cfg)
    )


def _metadata_from_config(
    state: Any,
    symbol: str,
    asset_class: str,
    instrument_type: InstrumentType | None,
) -> AssetMetadata | None:
    asset_cfg = _matching_metadata_row(
        [
            row
            for row in iter_configured_asset_metadata(state)
            if symbol in _asset_symbols(row)
        ],
        asset_class,
        instrument_type,
        allow_legacy_names=True,
    )
    if asset_cfg is not None:
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


def _metadata_from_db(
    state: Any,
    symbol: str,
    asset_class: str,
    instrument_type: InstrumentType | None,
) -> AssetMetadata | None:
    db = getattr(state, "db", None)
    get_metadata = getattr(db, "get_instrument_metadata_sync", None)
    if not callable(get_metadata):
        return None
    try:
        if instrument_type is not None:
            kinds = [instrument_type.value]
            if instrument_type is InstrumentType.OPEN_END_FUND:
                kinds.append("fund")
        elif asset_class == "fund":
            kinds = ["etf", "open_end_fund", "fund"]
        else:
            kinds = [None if asset_class == "other" else asset_class]
        if (
            asset_class == "other"
            and instrument_type is None
            and callable(getattr(db, "list_instrument_metadata_sync", None))
        ):
            rows = [
                row
                for row in _db_metadata_entries(state)
                if row.get("symbol") == symbol
            ]
        else:
            rows = [
                row
                for kind in kinds
                if isinstance(row := get_metadata(symbol, kind), dict)
            ]
    except Exception:
        return None
    row = _matching_metadata_row(rows, asset_class, instrument_type)
    if row is None:
        return None
    display_name = str(row.get("display_name") or "").strip()
    if not display_name:
        return None
    return AssetMetadata(
        symbol=symbol,
        display_name=display_name,
        asset_class=_normalize_asset_class(
            row.get("asset_type") or row.get("asset_class")
        )
        or asset_class,
        market=row.get("market"),
        provider=row.get("provider_name") or row.get("provider"),
        provider_symbol=row.get("provider_symbol"),
        source="db",
    )


def _db_metadata_entries(state: Any) -> list[dict[str, Any]]:
    db = getattr(state, "db", None)
    list_metadata = getattr(db, "list_instrument_metadata_sync", None)
    if not callable(list_metadata):
        return []
    try:
        rows = list_metadata() or []
    except Exception:
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _db_watchlist_entries(state: Any) -> list[dict[str, Any]]:
    db = getattr(state, "db", None)
    list_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    if not callable(list_watchlist):
        return []
    try:
        rows = list_watchlist() or []
    except Exception:
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _watchlist_symbols(state: Any) -> set[tuple[str, str | None]]:
    scheduler = getattr(state, "scheduler", None)
    symbols: set[tuple[str, str | None]] = set()
    for item in getattr(scheduler, "watchlist", []) or []:
        if isinstance(item, (list, tuple)) and item:
            symbol = str(item[0])
            asset_class = item[1] if len(item) > 1 else None
            symbols.add((symbol, _normalize_asset_class(asset_class)))
    for row in _db_watchlist_entries(state):
        symbol = str(row.get("symbol") or "").strip()
        if symbol:
            symbols.add((symbol, _normalize_asset_class(row.get("asset_class"))))
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
                    symbols.add(
                        (symbol, _normalize_asset_class(quote.get("asset_class")))
                    )
        except Exception:
            pass
    return symbols


def build_asset_metadata_status(state: Any) -> dict[str, Any]:
    """Summarize configured and missing asset identities for Settings."""
    configured_entries = iter_configured_asset_metadata(state)
    db_entries = _db_metadata_entries(state)
    watchlist_entries = _db_watchlist_entries(state)
    configured_assets: list[dict[str, Any]] = []
    seen_identities: set[tuple[str, str]] = set()
    configured_symbols: set[str] = set()
    for row in db_entries:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        asset_class = _normalize_asset_class(
            row.get("asset_type") or row.get("asset_class")
        )
        if (symbol, asset_class) in seen_identities:
            continue
        seen_identities.add((symbol, asset_class))
        configured_symbols.add(symbol)
        configured_assets.append(
            {
                "symbol": symbol,
                "display_name": str(row.get("display_name") or symbol),
                "asset_class": asset_class,
                "provider_symbol": row.get("provider_symbol"),
                "aliases": [],
                "source": row.get("source") or "db",
            }
        )
    for row in watchlist_entries:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        asset_class = _normalize_asset_class(row.get("asset_class"))
        if (symbol, asset_class) in seen_identities or symbol in configured_symbols:
            continue
        display_name = str(row.get("display_name") or symbol).strip()
        if not display_name:
            continue
        seen_identities.add((symbol, asset_class))
        configured_symbols.add(symbol)
        configured_assets.append(
            {
                "symbol": symbol,
                "display_name": display_name,
                "asset_class": asset_class,
                "provider_symbol": row.get("provider_symbol"),
                "aliases": [],
                "source": row.get("source") or "watchlist",
            }
        )
    for cfg in configured_entries:
        symbols = _asset_symbols(cfg)
        configured_symbols.update(symbols)
        primary_symbol = str(cfg.get("symbol") or next(iter(symbols), "")).strip()
        if not primary_symbol:
            continue
        asset_class = _normalize_asset_class(cfg.get("asset_class"))
        if (primary_symbol, asset_class) in seen_identities:
            continue
        seen_identities.add((primary_symbol, asset_class))
        configured_assets.append(
            {
                "symbol": primary_symbol,
                "display_name": str(
                    cfg.get("display_name") or cfg.get("name") or primary_symbol
                ),
                "asset_class": asset_class,
                "provider_symbol": cfg.get("provider_symbol")
                or cfg.get("provider_code")
                or cfg.get("code"),
                "aliases": sorted(symbols - {primary_symbol}),
                "source": cfg.get("source") or "config",
            }
        )

    observed = (
        _position_symbols(state) | _watchlist_symbols(state) | _quote_symbols(state)
    )
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
        "configured_count": len(configured_assets),
        "configured_assets": configured_assets,
        "missing_symbols": missing_symbols,
        "suggested_config": {"watchlist_assets": suggested_assets},
        "metadata_source": "db+watchlist+legacy_config",
        "has_missing_metadata": bool(missing_symbols),
    }


def _metadata_from_watchlist(
    state: Any,
    symbol: str,
    asset_class: str,
    instrument_type: InstrumentType | None,
) -> AssetMetadata | None:
    row = _matching_metadata_row(
        [
            row
            for row in _db_watchlist_entries(state)
            if str(row.get("symbol") or "").strip() == symbol
        ],
        asset_class,
        instrument_type,
    )
    if row is not None:
        display_name = str(row.get("display_name") or "").strip()
        if not display_name:
            return None
        return AssetMetadata(
            symbol=symbol,
            display_name=display_name,
            asset_class=_normalize_asset_class(row.get("asset_class")) or asset_class,
            source=row.get("source") or "watchlist",
        )
    return None


def _metadata_from_instrument(
    state: Any,
    symbol: str,
    asset_class: str,
    instrument_type: InstrumentType | None,
) -> AssetMetadata | None:
    scheduler = getattr(state, "scheduler", None)
    instruments = getattr(scheduler, "instruments", {}) if scheduler else {}
    instrument = instruments.get(Symbol(symbol)) or instruments.get(symbol)
    if instrument is None:
        return None
    name = str(getattr(instrument, "name", "") or "").strip()
    if not name:
        return None
    row = _matching_metadata_row(
        [
            {
                "instrument_type": getattr(instrument, "instrument_type", None),
                "asset_class": getattr(instrument, "asset_class", None),
            }
        ],
        asset_class,
        instrument_type,
    )
    if row is None:
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
    instrument_type: InstrumentType | None,
) -> AssetMetadata | None:
    if not quote:
        return None
    if quote.get("symbol") and str(quote["symbol"]) != symbol:
        return None
    if _matching_metadata_row([quote], asset_class, instrument_type) is None:
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
    asset_class: AssetClass | str | None = None,
    instrument_type: InstrumentType | str | None = None,
    quote: dict[str, Any] | None = None,
    fallback_name: str | None = None,
) -> AssetMetadata:
    """Resolve a stable display identity without hardcoding UI names."""
    normalized_asset_class = _normalize_asset_class(asset_class)
    raw_type = instrument_type
    if raw_type is None and normalized_asset_class not in {"fund", "other", "cash"}:
        raw_type = normalized_asset_class
    if raw_type is None and getattr(asset_class, "value", asset_class) in {
        "open_end_fund",
        "openend_fund",
    }:
        raw_type = asset_class
    try:
        exact_type = (
            InstrumentType.from_persisted(raw_type) if raw_type is not None else None
        )
    except ValueError:
        exact_type = InstrumentType.UNKNOWN
    if normalized_asset_class == "other" and exact_type not in {
        None,
        InstrumentType.UNKNOWN,
    }:
        normalized_asset_class = _normalize_asset_class(exact_type.value)
        if normalized_asset_class == "etf":
            normalized_asset_class = "fund"
    candidate = (
        _metadata_from_db(state, symbol, normalized_asset_class, exact_type)
        or _metadata_from_watchlist(state, symbol, normalized_asset_class, exact_type)
        or _metadata_from_quote(symbol, normalized_asset_class, quote, exact_type)
        or _metadata_from_config(state, symbol, normalized_asset_class, exact_type)
        or _metadata_from_instrument(state, symbol, normalized_asset_class, exact_type)
    )
    if candidate is not None:
        return (
            replace(candidate, asset_class=normalized_asset_class)
            if normalized_asset_class != "other"
            else candidate
        )
    return AssetMetadata(
        symbol=symbol,
        display_name=fallback_name or symbol,
        asset_class=normalized_asset_class,
        source="fallback",
    )
