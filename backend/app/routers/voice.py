"""WebSocket entry point for the voice call."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket

from ..services.realtime_proxy import RealtimeBridge

router = APIRouter()
logger = logging.getLogger("voice")


@router.websocket("/voice")
async def voice_ws(ws: WebSocket) -> None:
    await ws.accept()
    bridge = RealtimeBridge(ws)
    try:
        await bridge.open()
    finally:
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
