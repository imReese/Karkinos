from __future__ import annotations

DEFAULT_MARKET_INDEX_ASSETS: tuple[dict[str, str], ...] = (
    {"symbol": "000001", "asset_class": "index", "display_name": "上证指数"},
    {"symbol": "399001", "asset_class": "index", "display_name": "深证成指"},
    {"symbol": "399006", "asset_class": "index", "display_name": "创业板指"},
    {"symbol": "000300", "asset_class": "index", "display_name": "沪深300"},
    {"symbol": "000905", "asset_class": "index", "display_name": "中证500"},
    {"symbol": "000016", "asset_class": "index", "display_name": "上证50"},
)


def default_market_index_assets() -> list[dict[str, str]]:
    """Return the default broad-market index universe for read-only context."""
    return [dict(asset) for asset in DEFAULT_MARKET_INDEX_ASSETS]


def market_index_display_name(symbol: str) -> str | None:
    """Return the configured display name for a default broad-market index."""
    for asset in DEFAULT_MARKET_INDEX_ASSETS:
        if asset["symbol"] == symbol:
            return asset["display_name"]
    return None
