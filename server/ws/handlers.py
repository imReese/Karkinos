"""WebSocket 端点 /ws — 实时事件推送。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.ws.hub import ConnectionHub

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket 端点：将 EventBus 事件实时推送到浏览器。"""
    hub: ConnectionHub = ws.app.state.hub
    await hub.connect(ws)
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        hub.disconnect(ws)
