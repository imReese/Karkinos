from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import AssetClass, BarFrequency, Symbol
from server.bridge import EventBusBridge


def test_event_bus_bridge_serializes_market_event_symbol() -> None:
    loop = asyncio.new_event_loop()
    bridge = EventBusBridge(EventBus(), loop)
    event = MarketEvent(
        timestamp=datetime(2026, 6, 5, 10, 30),
        symbol=Symbol("600001"),
        open=Decimal("9.25"),
        high=Decimal("9.25"),
        low=Decimal("9.25"),
        close=Decimal("9.25"),
        volume=Decimal("1000"),
        frequency=BarFrequency.DAILY,
        asset_class=AssetClass.STOCK,
    )

    try:
        payload = bridge._serialize(event)
    finally:
        loop.close()

    assert payload["event_type"] == "MarketEvent"
    assert payload["symbol"] == "600001"
    assert payload["close"] == 9.25
    assert payload["frequency"] == "1d"
    assert payload["asset_class"] == "stock"
