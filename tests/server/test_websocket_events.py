"""Real WebSocket delivery shares one broadcast consumer across connections."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal

from fastapi import FastAPI

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import Symbol
from server.app import _forward_events
from server.bridge import EventBusBridge
from server.ws.handlers import router
from server.ws.hub import ConnectionHub


def _scope() -> dict:
    return {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": "/ws",
        "raw_path": b"/ws",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "subprotocols": [],
    }


async def _connect(app: FastAPI):
    incoming: asyncio.Queue[dict] = asyncio.Queue()
    outgoing: asyncio.Queue[dict] = asyncio.Queue()
    await incoming.put({"type": "websocket.connect"})
    task = asyncio.create_task(app(_scope(), incoming.get, outgoing.put))
    assert (await asyncio.wait_for(outgoing.get(), 1))["type"] == "websocket.accept"
    return incoming, outgoing, task


def test_every_websocket_receives_each_event_bus_broadcast() -> None:
    async def run():
        app = FastAPI()
        app.include_router(router)
        bus = EventBus()
        hub = ConnectionHub()
        bridge = EventBusBridge(bus, asyncio.get_running_loop())
        app.state.hub = hub
        app.state.bridge = bridge
        bridge.start()
        forward = asyncio.create_task(_forward_events(bridge, hub))
        sessions = []
        try:
            await asyncio.sleep(0)
            sessions.extend([await _connect(app), await _connect(app)])
            assert hub.connection_count == 2
            for symbol in ("600001", "600002", "600003"):
                bus.publish_and_process(
                    MarketEvent(
                        timestamp=datetime(2026, 6, 5, 10, 30),
                        symbol=Symbol(symbol),
                        open=Decimal("9.25"),
                        high=Decimal("9.25"),
                        low=Decimal("9.25"),
                        close=Decimal("9.25"),
                        volume=Decimal("1000"),
                    )
                )
                frames = await asyncio.wait_for(
                    asyncio.gather(*(outgoing.get() for _, outgoing, _ in sessions)),
                    1,
                )
                for frame in frames:
                    assert frame["type"] == "websocket.send"
                    payload = json.loads(frame["text"])
                    assert payload["event_type"] == "MarketEvent"
                    assert payload["symbol"] == symbol
                    assert payload["close"] == 9.25
        finally:
            for incoming, _, task in sessions:
                await incoming.put({"type": "websocket.disconnect", "code": 1000})
                task.cancel()
            await asyncio.gather(
                *(task for _, _, task in sessions), return_exceptions=True
            )
            forward.cancel()
            await asyncio.gather(forward, return_exceptions=True)
            bridge.stop()

    asyncio.run(run())


def test_idle_websocket_disconnect_unregisters_without_another_market_event() -> None:
    async def run():
        app = FastAPI()
        app.include_router(router)
        hub = ConnectionHub()
        bridge = EventBusBridge(EventBus(), asyncio.get_running_loop())
        app.state.hub = hub
        app.state.bridge = bridge
        incoming, _, task = await _connect(app)
        try:
            assert hub.connection_count == 1
            await incoming.put({"type": "websocket.disconnect", "code": 1000})
            await asyncio.wait_for(asyncio.shield(task), 1)
            assert hub.connection_count == 0
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_broadcast_keeps_remaining_connections_when_one_disconnects_during_send() -> (
    None
):
    async def run():
        hub = ConnectionHub()
        received = []

        class Connection:
            async def accept(self):
                pass

            async def send_json(self, data):
                received.append((self, data))
                if self is first:
                    hub.disconnect(self)

        first, second = Connection(), Connection()
        await hub.connect(first)
        await hub.connect(second)
        event = {"event_type": "MarketEvent", "symbol": "600001"}

        await hub.broadcast(event)

        assert received == [(first, event), (second, event)]
        assert hub.connection_count == 1

    asyncio.run(run())
