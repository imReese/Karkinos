"""WebSocket 端点 /ws — 实时事件推送。"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.dependencies import get_bridge, get_hub
from server.ws.hub import ConnectionHub

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket 端点：将 EventBus 事件实时推送到浏览器。"""
    hub: ConnectionHub = ws.app.state.hub
    await hub.connect(ws)
    bridge = ws.app.state.bridge

    try:
        while True:
            event_data = await bridge.get_event()
            await ws.send_json(event_data)
    except WebSocketDisconnect:
        hub.disconnect(ws)
    except Exception:
        logger.exception("WebSocket error")
        hub.disconnect(ws)
