from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import websockets
from sentence_transformers import SentenceTransformer

from evals.config import config
from evals.harnesses.websocket_client import WebSocketClient

ROOT = config.root_dir
DATA_DIR = config.data_dir
REPORT_DIR = config.report_dir
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def similarity_model() -> SentenceTransformer:
    return SentenceTransformer("all-MiniLM-L6-v2")


def read_json(name: str) -> dict[str, Any]:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


async def fetch_json(url: str, method: str = "get", **kwargs: Any) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        response = await getattr(client, method)(url, **kwargs)
        response.raise_for_status()
        return response.json()


async def websocket_turn(session_id: str, message: str, user_id: str | None = None) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    async with WebSocketClient(session_id) as client:
        result = await client.send_text(message, user_id=user_id)
        return result.text, result.audio_chunks, result.tool_calls, result.latency_breakdown


async def websocket_audio_turn(session_id: str, audio_bytes: bytes, audio_format: str = "wav") -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    async with WebSocketClient(session_id) as client:
        result = await client.send_audio(audio_bytes, audio_format=audio_format)
        return result.text, result.audio_chunks, result.tool_calls, result.latency_breakdown
