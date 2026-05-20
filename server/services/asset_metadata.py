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


def metadata_configured_count(state: Any) -> int:
    """Count configured asset identities that carry useful display metadata."""
    count = 0
    for asset_cfg in getattr(state.config, "assets", []):
        if any(
            str(asset_cfg.get(key) or "").strip()
            for key in (
                "display_name",
                "name",
                "provider_symbol",
                "provider_code",
                "provider",
                "code",
            )
        ):
            count += 1
    return count


def _metadata_from_config(
    state: Any,
    symbol: str,
    asset_class: str,
) -> AssetMetadata | None:
    for asset_cfg in getattr(state.config, "assets", []):
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
