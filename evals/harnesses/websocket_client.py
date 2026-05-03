from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from typing import Any

import websockets

from evals.config import config


@dataclass
class TurnResult:
    text: str = ""
    audio_chunks: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    latency_breakdown: dict[str, Any] = field(default_factory=dict)
    first_text_ms: float | None = None
    first_audio_ms: float | None = None
    end_ms: float | None = None


class WebSocketClient:
    """Small websocket harness for the live assistant."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.uri = f"{config.WS_URL}/{session_id}"
        self._ws: Any = None

    async def __aenter__(self) -> "WebSocketClient":
        self._ws = await websockets.connect(self.uri, ping_interval=None, close_timeout=20)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._ws is not None:
            await self._ws.close()

    async def send_text(self, message: str, user_id: str | None = None) -> TurnResult:
        payload: dict[str, Any] = {"type": "text_input", "content": message}
        if user_id:
            payload["user_id"] = user_id
        await self._ws.send(json.dumps(payload))
        return await self._collect_turn()

    async def send_audio(self, audio_bytes: bytes, audio_format: str = "wav", user_id: str | None = None) -> TurnResult:
        payload: dict[str, Any] = {
            "type": "audio_input",
            "audio": base64.b64encode(audio_bytes).decode("ascii"),
            "format": audio_format,
        }
        if user_id:
            payload["user_id"] = user_id
        await self._ws.send(json.dumps(payload))
        return await self._collect_turn()

    async def _collect_turn(self) -> TurnResult:
        result = TurnResult()
        started = asyncio.get_event_loop().time()
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=120.0)
            msg = json.loads(raw)
            result.messages.append(msg)
            msg_type = msg.get("type")
            if msg_type == "text_chunk":
                if result.first_text_ms is None:
                    result.first_text_ms = (asyncio.get_event_loop().time() - started) * 1000.0
                result.text += msg.get("content", "")
            elif msg_type == "audio_chunk":
                if result.first_audio_ms is None:
                    result.first_audio_ms = (asyncio.get_event_loop().time() - started) * 1000.0
                result.audio_chunks.append(msg)
            elif msg_type == "tool_call":
                result.tool_calls.append(msg)
            elif msg_type == "turn_complete":
                result.latency_breakdown = msg.get("latency_breakdown", {})
                result.end_ms = (asyncio.get_event_loop().time() - started) * 1000.0
                break
            elif msg_type == "error":
                result.end_ms = (asyncio.get_event_loop().time() - started) * 1000.0
                break
        return result
