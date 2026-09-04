"""Canonical persisted-quote restoration for the scheduler runtime."""

from __future__ import annotations

from typing import Any

from core.types import AssetClass, InstrumentType, Symbol
from domain.instrument import Instrument

INSTRUMENT_ASSET_CLASS_MAP = {
    InstrumentType.STOCK: AssetClass.STOCK,
    InstrumentType.ETF: AssetClass.FUND,
    InstrumentType.OPEN_END_FUND: AssetClass.FUND,
    InstrumentType.GOLD: AssetClass.GOLD,
    InstrumentType.BOND: AssetClass.BOND,
    InstrumentType.INDEX: AssetClass.INDEX,
}


def runtime_quote_from_persisted(quote: dict[str, Any]) -> dict[str, Any]:
    """Normalize one persisted latest-quote row for scheduler runtime use."""

    quote_source = (
        quote.get("quote_source")
        or quote.get("source")
        or quote.get("provider_name")
        or quote.get("provider")
    )
    persisted_asset_type = (
        str(quote.get("asset_type") or quote.get("asset_class") or "")
        .strip()
        .lower()
        .replace("-", "_")
    )
    raw_instrument_type = (
        str(
            quote.get("instrument_type")
            or quote.get("asset_type")
            or quote.get("asset_class")
            or ""
        )
        .strip()
        .lower()
        .replace("-", "_")
    )
    instrument_type = InstrumentType.from_persisted(raw_instrument_type)
    asset_class = INSTRUMENT_ASSET_CLASS_MAP[instrument_type]
    return {
        "price": float(quote["price"]),
        "volume": float(quote["volume"]) if quote["volume"] is not None else None,
        "timestamp": quote["timestamp"],
        "asset_class": asset_class.value,
        "instrument_type": instrument_type.value,
        "identity_provenance": (
            quote.get("identity_provenance")
            or (
                "legacy_fund_compatibility"
                if persisted_asset_type == "fund"
                else "persisted_canonical"
            )
        ),
        "quote_source": quote_source,
        "provider_name": quote.get("provider_name"),
        "quote_status": quote.get("quote_status"),
        "stale_reason": quote.get("stale_reason"),
        "provider_status": quote.get("provider_status"),
        "captured_reason": quote.get("captured_reason"),
        "nav_date": quote.get("nav_date"),
    }


def runtime_quotes_from_persisted(
    quotes: list[dict[str, Any]],
    instruments: dict[Symbol, Instrument],
) -> dict[str, dict[str, Any]]:
    """Bind restored quotes to canonical runtime identities."""

    expected = {
        str(symbol): instrument.instrument_type
        for symbol, instrument in instruments.items()
    }
    selected: dict[str, tuple[InstrumentType, dict[str, Any], tuple[str, str, int]]] = (
        {}
    )
    for quote in quotes:
        symbol = str(quote.get("symbol") or "").strip()
        if not symbol:
            raise RuntimeError("persisted scheduler quote contains no symbol")
        raw_type = (
            quote.get("instrument_type")
            or quote.get("asset_type")
            or quote.get("asset_class")
        )
        try:
            instrument_type = InstrumentType.from_persisted(raw_type)
        except ValueError as exc:
            raise RuntimeError(
                f"persisted scheduler quote identity is unresolved: {symbol}"
            ) from exc
        expected_type = expected.get(symbol)
        if expected_type is not None and instrument_type is not expected_type:
            continue
        rank = (
            str(quote.get("quote_timestamp") or quote.get("timestamp") or ""),
            str(quote.get("updated_at") or quote.get("captured_at") or ""),
            int(quote.get("id") or 0),
        )
        previous = selected.get(symbol)
        if previous is not None and previous[0] is not instrument_type:
            raise RuntimeError(
                f"persisted scheduler quote identity conflicts: {symbol}"
            )
        if previous is None or rank > previous[2]:
            selected[symbol] = (instrument_type, quote, rank)
    return {
        symbol: runtime_quote_from_persisted(quote)
        for symbol, (_, quote, _) in selected.items()
    }


__all__ = [
    "INSTRUMENT_ASSET_CLASS_MAP",
    "runtime_quote_from_persisted",
    "runtime_quotes_from_persisted",
]
