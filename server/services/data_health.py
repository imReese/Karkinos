from __future__ import annotations


def build_data_health(watchlist, latest_quotes, bar_coverage):
    quotes = []
    bars = []

    for symbol, asset_class in watchlist:
        symbol_str = str(symbol)
        quote = latest_quotes.get(symbol_str)
        coverage = bar_coverage.get(symbol_str, {})

        quotes.append(
            {
                "symbol": symbol_str,
                "asset_class": str(asset_class),
                "timestamp": None if quote is None else quote.get("timestamp"),
                "price": None if quote is None else quote.get("price"),
            }
        )
        bars.append(
            {
                "symbol": symbol_str,
                "start": coverage.get("start"),
                "end": coverage.get("end"),
                "rows": coverage.get("rows", 0),
            }
        )

    return {"quotes": quotes, "bars": bars}
