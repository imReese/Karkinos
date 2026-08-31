"""Read-only display identities for verified research operation previews."""

from __future__ import annotations

from typing import Any, Mapping


RESEARCH_OPERATION_INSTRUMENTS_SCHEMA_VERSION = (
    "karkinos.decision.research_operation_instruments.v1"
)
_MAX_LOOKUP_SYMBOLS = 40


def build_research_operation_instruments(
    db: Any,
    preview: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Join persisted names without changing strategy evidence or authority."""

    operations = (
        preview.get("operations")
        if isinstance(preview, Mapping) and preview.get("status") == "available"
        else []
    )
    prioritized_operations = sorted(
        (item for item in operations or [] if isinstance(item, Mapping)),
        key=lambda item: item.get("operation") != "buy_candidate",
    )
    requested_symbols: list[str] = []
    for operation in prioritized_operations:
        symbol = str(operation.get("symbol") or "").strip()
        if symbol and symbol not in requested_symbols:
            requested_symbols.append(symbol)

    lookup_symbols = requested_symbols[:_MAX_LOOKUP_SYMBOLS]
    rows: list[dict[str, Any]] = []
    batch_lookup = getattr(db, "get_instrument_metadata_batch_sync", None)
    if callable(batch_lookup) and lookup_symbols:
        try:
            result = batch_lookup(lookup_symbols, "stock") or []
        except Exception:
            result = []
        rows = [dict(row) for row in result if isinstance(row, Mapping)]

    by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip()
        display_name = str(row.get("display_name") or "").strip()
        if (
            symbol in lookup_symbols
            and display_name
            and display_name != symbol
            and display_name != f"{symbol} A股"
        ):
            by_symbol[symbol] = {
                "symbol": symbol,
                "display_name": display_name,
                "asset_class": "stock",
                "source": str(row.get("source") or "instrument_metadata"),
                "fetched_at": row.get("fetched_at"),
            }

    items = [by_symbol[symbol] for symbol in requested_symbols if symbol in by_symbol]
    missing_symbols = [
        symbol for symbol in requested_symbols if symbol not in by_symbol
    ]
    return {
        "schema_version": RESEARCH_OPERATION_INSTRUMENTS_SCHEMA_VERSION,
        "requested_count": len(requested_symbols),
        "lookup_count": len(lookup_symbols),
        "resolved_count": len(items),
        "items": items,
        "missing_symbols": missing_symbols,
        "lookup_truncated": len(requested_symbols) > len(lookup_symbols),
        "metadata_source": "persisted_instrument_metadata",
        "provider_contacted": False,
        "database_writes_performed": False,
        "read_only": True,
        "research_only": True,
        "authority_effect": "none",
    }


__all__ = (
    "RESEARCH_OPERATION_INSTRUMENTS_SCHEMA_VERSION",
    "build_research_operation_instruments",
)
