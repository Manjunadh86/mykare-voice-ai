"""Bidirectional WebSocket proxy between the browser and the OpenAI Realtime API.

Why a proxy and not a direct browser connection?
------------------------------------------------
1. Security: the OpenAI API key never touches the browser.
2. Tool execution: tool calls run server-side against our SQLite DB.
3. Persistence: we write transcript + tool-call logs as the call happens.
4. Cost tracking: we accumulate audio seconds & token counts per session.

Wire protocol
-------------
Browser  ←→  Backend (this proxy)  ←→  OpenAI Realtime API

Browser → Backend (JSON over WS):
  {"type": "input_audio_buffer.append", "audio": "<base64 PCM16>"}  - mic frames
  {"type": "input_audio_buffer.commit"}                              - end of turn
  {"type": "response.create"}                                        - request reply
  {"type": "session.end"}                                            - close call

Backend → Browser (JSON over WS), passes through OpenAI events plus extras:
  {"type": "session.id", "session_id": "..."}                        - first event
  {"type": "tool.call.started", "name": "...", "arguments": {...}}   - UI hint
  {"type": "tool.call.completed", "name": "...", "result": {...}}    - UI hint
  {"type": "response.audio.delta", "delta": "<base64 PCM16>"}        - speech
  {"type": "response.audio_transcript.delta", "delta": "..."}        - assistant text
  {"type": "conversation.item.input_audio_transcription.completed"}  - user text
  {"type": "session.cost.update", "cost": {...}}                     - live cost
  {"type": "session.end_call"}                                       - graceful end
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from typing import Any, Dict, Optional

import websockets
from websockets.asyncio.client import (
    ClientConnection as _AsyncWSClient,
    connect as ws_connect,
)
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import session_scope
from ..models import Message, Session as DBSession
from ..tools import TOOL_SCHEMAS, build_system_prompt, dispatch_tool

logger = logging.getLogger("realtime_proxy")
settings = get_settings()

OPENAI_REALTIME_URL = (
    "wss://api.openai.com/v1/realtime?model={model}"
)


class RealtimeBridge:
    """One bridge per browser WebSocket connection."""

    def __init__(self, browser_ws: WebSocket) -> None:
        self.browser_ws = browser_ws
        self.openai_ws: Optional[_AsyncWSClient] = None
        self.session_id: str = uuid.uuid4().hex
        self.upstream_task: Optional[asyncio.Task] = None
        self.downstream_task: Optional[asyncio.Task] = None
        self.closed = False

        # Cost / usage trackers
        self.audio_input_ms = 0
        self.audio_output_ms = 0
        self.text_input_tokens = 0
        self.text_output_tokens = 0

        # Transcript buffers (assistant text streams in deltas)
        self._assistant_buffer: str = ""
        self._user_buffer: str = ""

    # ---- lifecycle ----

    async def open(self) -> None:
        if not settings.openai_api_key:
            await self.browser_ws.send_json(
                {
                    "type": "error",
                    "message": (
                        "OPENAI_API_KEY not set on the server. "
                        "Add it to backend/.env and restart."
                    ),
                }
            )
            await self.browser_ws.close()
            return

        url = OPENAI_REALTIME_URL.format(model=settings.openai_realtime_model)
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        try:
            self.openai_ws = await ws_connect(
                url,
                additional_headers=headers,
                max_size=8 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=20,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to connect to OpenAI Realtime")
            await self.browser_ws.send_json(
                {"type": "error", "message": f"Could not connect to OpenAI: {exc}"}
            )
            await self.browser_ws.close()
            return

        # Persist a session row
        async with session_scope() as db:
            db.add(DBSession(id=self.session_id))

        await self.browser_ws.send_json(
            {"type": "session.id", "session_id": self.session_id}
        )

        await self._configure_openai_session()

        # Have the assistant kick off the conversation with a greeting.
        await self.openai_ws.send(json.dumps({"type": "response.create"}))

        self.upstream_task = asyncio.create_task(self._pump_browser_to_openai())
        self.downstream_task = asyncio.create_task(self._pump_openai_to_browser())

        await asyncio.gather(
            self.upstream_task, self.downstream_task, return_exceptions=True
        )

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for t in (self.upstream_task, self.downstream_task):
            if t and not t.done():
                t.cancel()
        if self.openai_ws is not None:
            try:
                await self.openai_ws.close()
            except Exception:  # noqa: BLE001
                pass
        # Persist final cost
        await self._persist_session_close()

    # ---- configuration ----

    async def _configure_openai_session(self) -> None:
        """Send the initial session.update with our tools, voice, instructions."""
        assert self.openai_ws is not None
        cfg = {
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "instructions": build_system_prompt(),
                "voice": settings.openai_realtime_voice,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                # Tightened VAD so faint echo from speakers (Aria hearing her
                # own voice through the user's mic) doesn't trigger spurious
                # turns. If the user's on headphones this can be relaxed.
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.75,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 900,
                    "create_response": True,
                },
                "tools": TOOL_SCHEMAS,
                "tool_choice": "auto",
                "temperature": 0.7,
                "max_response_output_tokens": 4096,
            },
        }
        await self.openai_ws.send(json.dumps(cfg))

    # ---- pump: browser → openai ----

    async def _pump_browser_to_openai(self) -> None:
        try:
            while not self.closed:
                msg = await self.browser_ws.receive_text()
                data = json.loads(msg)
                mtype = data.get("type")

                if mtype == "session.end":
                    break

                if mtype == "input_audio_buffer.append":
                    # Track input audio length (rough estimate from base64 size)
                    audio_b64 = data.get("audio", "")
                    bytes_len = (len(audio_b64) * 3) // 4
                    # PCM16 mono @ 24kHz → 48000 bytes/sec
                    self.audio_input_ms += int(bytes_len / 48)

                # Forward all browser events to OpenAI (whitelisted by event type)
                if self.openai_ws is not None and mtype:
                    await self.openai_ws.send(json.dumps(data))
        except WebSocketDisconnect:
            logger.info("Browser disconnected")
        except Exception:  # noqa: BLE001
            logger.exception("upstream pump crashed")
        finally:
            await self.close()

    # ---- pump: openai → browser ----

    async def _pump_openai_to_browser(self) -> None:
        assert self.openai_ws is not None
        try:
            async for raw in self.openai_ws:
                if self.closed:
                    break
                try:
                    evt = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                etype = evt.get("type", "")

                # ---- usage / cost tracking ----
                if etype == "response.done":
                    usage = (evt.get("response") or {}).get("usage") or {}
                    self.text_input_tokens += int(usage.get("input_tokens", 0) or 0)
                    self.text_output_tokens += int(usage.get("output_tokens", 0) or 0)
                    out_audio_ms = (
                        usage.get("output_token_details", {}).get("audio_tokens", 0) or 0
                    )
                    # rough conversion: ~25 audio tokens ≈ 1 sec ≈ 1000ms
                    self.audio_output_ms += int(out_audio_ms * 40)
                    await self._send_cost_update()

                # ---- transcript persistence ----
                if etype == "response.audio_transcript.delta":
                    self._assistant_buffer += evt.get("delta", "")
                elif etype == "response.audio_transcript.done":
                    text = self._assistant_buffer.strip()
                    self._assistant_buffer = ""
                    if text:
                        await self._save_message("assistant", text)
                elif (
                    etype
                    == "conversation.item.input_audio_transcription.completed"
                ):
                    text = (evt.get("transcript") or "").strip()
                    if text:
                        await self._save_message("user", text)

                # ---- tool calls ----
                if etype == "response.function_call_arguments.done":
                    await self._handle_function_call(evt)
                    # We don't forward the raw event to the browser (we send our
                    # own friendlier `tool.call.completed` event).
                    continue

                if etype == "response.output_item.added":
                    item = evt.get("item") or {}
                    if item.get("type") == "function_call":
                        await self.browser_ws.send_json(
                            {
                                "type": "tool.call.started",
                                "name": item.get("name"),
                                "call_id": item.get("call_id"),
                            }
                        )

                # Forward to the browser
                try:
                    await self.browser_ws.send_text(raw)
                except Exception:
                    break
        except websockets.ConnectionClosed:
            logger.info("OpenAI socket closed")
        except Exception:  # noqa: BLE001
            logger.exception("downstream pump crashed")
        finally:
            await self.close()

    # ---- function call handling ----

    async def _handle_function_call(self, evt: Dict[str, Any]) -> None:
        assert self.openai_ws is not None
        call_id = evt.get("call_id")
        name = evt.get("name")
        try:
            args = json.loads(evt.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}

        async with session_scope() as db:
            result = await dispatch_tool(name, args, db, self.session_id)

        # Send the function output back to OpenAI so it can speak the result
        await self.openai_ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result, default=str),
                    },
                }
            )
        )
        # Ask the model to respond using that tool output
        await self.openai_ws.send(json.dumps({"type": "response.create"}))

        # Tell the UI
        await self.browser_ws.send_json(
            {
                "type": "tool.call.completed",
                "name": name,
                "arguments": args,
                "result": result,
                "call_id": call_id,
            }
        )

        # If the tool says it's time to end, signal the frontend to disconnect
        # AFTER the assistant's farewell finishes playing.
        if result.get("end_call"):
            await self.browser_ws.send_json({"type": "session.end_call"})

    # ---- persistence ----

    async def _save_message(self, role: str, content: str) -> None:
        async with session_scope() as db:
            db.add(Message(session_id=self.session_id, role=role, content=content))

    def _compute_cost(self) -> Dict[str, Any]:
        ai_min = self.audio_input_ms / 60000.0
        ao_min = self.audio_output_ms / 60000.0
        ti_cost = (self.text_input_tokens / 1000.0) * settings.cost_text_input_per_1k
        to_cost = (self.text_output_tokens / 1000.0) * settings.cost_text_output_per_1k
        ai_cost = ai_min * settings.cost_audio_input_per_min
        ao_cost = ao_min * settings.cost_audio_output_per_min
        total = ai_cost + ao_cost + ti_cost + to_cost
        return {
            "audio_input_min": round(ai_min, 4),
            "audio_output_min": round(ao_min, 4),
            "text_input_tokens": self.text_input_tokens,
            "text_output_tokens": self.text_output_tokens,
            "audio_input_cost": round(ai_cost, 4),
            "audio_output_cost": round(ao_cost, 4),
            "text_input_cost": round(ti_cost, 4),
            "text_output_cost": round(to_cost, 4),
            "total_cost_usd": round(total, 4),
        }

    async def _send_cost_update(self) -> None:
        try:
            await self.browser_ws.send_json(
                {"type": "session.cost.update", "cost": self._compute_cost()}
            )
        except Exception:  # noqa: BLE001
            pass

    async def _persist_session_close(self) -> None:
        from datetime import datetime, timezone

        cost = self._compute_cost()
        async with session_scope() as db:
            sess = await db.get(DBSession, self.session_id)
            if sess is None:
                return
            sess.ended_at = datetime.now(timezone.utc)
            sess.audio_input_ms = self.audio_input_ms
            sess.audio_output_ms = self.audio_output_ms
            sess.text_input_tokens = self.text_input_tokens
            sess.text_output_tokens = self.text_output_tokens
            sess.estimated_cost_usd = cost["total_cost_usd"]
