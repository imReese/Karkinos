"""Canonical instrument identity resolution for market refresh operations."""

from __future__ import annotations

from core.types import AssetClass, InstrumentType, Symbol


def is_real_persistent_quote(quote: dict | None) -> bool:
    return bool(quote and quote.get("price") not in {None, ""})


def instrument_type_for_refresh(
    state,
    symbol: str,
    raw_identity: object,
) -> InstrumentType:
    """Resolve refresh identity from explicit metadata, never symbol shape."""

    candidates: set[InstrumentType] = set()
    scheduler = getattr(state, "scheduler", None)
    instruments = getattr(scheduler, "instruments", {}) if scheduler else {}
    instrument = instruments.get(Symbol(symbol)) or instruments.get(symbol)
    runtime_type = getattr(instrument, "instrument_type", None)
    if isinstance(runtime_type, InstrumentType):
        candidates.add(runtime_type)

    db = getattr(state, "db", None)
    list_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    if callable(list_watchlist):
        for row in list_watchlist() or []:
            if str(row.get("symbol") or "").strip() == symbol:
                candidates.add(
                    InstrumentType.from_persisted(
                        row.get("instrument_type") or row.get("asset_class")
                    )
                )

    config = getattr(state, "config", None)
    assets = getattr(config, "assets", ()) if config is not None else ()
    iterable = assets.items() if isinstance(assets, dict) else enumerate(assets)
    for key, asset in iterable:
        if not isinstance(asset, dict):
            continue
        configured_symbol = str(
            asset.get("symbol") or ("" if isinstance(key, int) else key)
        ).strip()
        if configured_symbol == symbol:
            candidates.add(
                InstrumentType.from_persisted(
                    asset.get("instrument_type") or asset.get("asset_class")
                )
            )

    raw_value = getattr(raw_identity, "value", raw_identity)
    normalized_raw = str(raw_value or "").strip().lower().replace("-", "_")
    if normalized_raw not in {"", "fund"}:
        candidates.add(InstrumentType.from_persisted(normalized_raw))
    if len(candidates) > 1:
        kinds = ",".join(sorted(item.value for item in candidates))
        raise ValueError(
            f"quote refresh instrument identity conflicts for {symbol}: {kinds}"
        )
    if candidates:
        return next(iter(candidates))
    if normalized_raw == "fund":
        raise ValueError(
            f"quote refresh fund instrument type is unresolved for {symbol}"
        )
    return InstrumentType.from_persisted(normalized_raw)


def provider_asset_class(instrument_type: InstrumentType) -> AssetClass:
    mapping = {
        InstrumentType.STOCK: AssetClass.STOCK,
        InstrumentType.ETF: AssetClass.FUND,
        InstrumentType.OPEN_END_FUND: AssetClass.FUND,
        InstrumentType.GOLD: AssetClass.GOLD,
        InstrumentType.BOND: AssetClass.BOND,
        InstrumentType.INDEX: AssetClass.INDEX,
    }
    try:
        return mapping[instrument_type]
    except KeyError as exc:
        raise ValueError(
            f"quote refresh instrument type is unsupported: {instrument_type.value}"
        ) from exc


def latest_persistent_real_quote(
    state,
    symbol: str,
    asset_class: AssetClass | str | None = None,
) -> dict | None:
    """Read only the persisted quote for the requested canonical identity."""

    if state.db is None:
        return None
    instrument_type = instrument_type_for_refresh(state, symbol, asset_class)
    get_latest_quote = getattr(state.db, "get_latest_quote_sync", None)
    if callable(get_latest_quote):
        row = get_latest_quote(symbol, instrument_type.value)
        return row if is_real_persistent_quote(row) else None
    get_latest_quotes = getattr(state.db, "get_latest_quotes_sync", None)
    if not callable(get_latest_quotes):
        return None
    for row in get_latest_quotes() or []:
        if str(row.get("symbol") or "").strip() != symbol:
            continue
        try:
            row_type = InstrumentType.from_persisted(
                row.get("instrument_type")
                or row.get("asset_type")
                or row.get("asset_class")
            )
        except ValueError:
            continue
        if row_type is instrument_type and is_real_persistent_quote(row):
            return row
    return None


__all__ = [
    "instrument_type_for_refresh",
    "is_real_persistent_quote",
    "latest_persistent_real_quote",
    "provider_asset_class",
]
