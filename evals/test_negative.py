from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest

from evals.config import config
from evals.harnesses.websocket_client import WebSocketClient


@pytest.mark.asyncio
async def test_invalid_ticker_does_not_crash() -> None:
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        resp = await client.get("/api/tools/stock_price", params={"ticker": "INVALIDTICKER999"})
        resp.raise_for_status()
        assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_empty_user_message_handled() -> None:
    async with WebSocketClient("eval_neg_empty_001") as client:
        turn = await client.send_text("")
    assert turn.text is not None


@pytest.mark.asyncio
async def test_malformed_audio_does_not_crash() -> None:
    fake_audio = base64.b64encode(b"this is not audio data").decode("ascii")
    async with WebSocketClient("eval_neg_audio_001") as client:
        await client._ws.send(json.dumps({"type": "audio_input", "audio": fake_audio, "format": "webm"}))
        msg = json.loads(await asyncio.wait_for(client._ws.recv(), timeout=30.0))
    assert msg["type"] in {"error", "transcription"}


@pytest.mark.asyncio
async def test_very_long_message_does_not_crash() -> None:
    long_msg = "tell me about apple " * 200
    async with WebSocketClient("eval_neg_long_001") as client:
        turn = await client.send_text(long_msg)
    assert len(turn.text) > 0


@pytest.mark.asyncio
async def test_company_not_in_corpus() -> None:
    async with WebSocketClient("eval_neg_corpus_001") as client:
        turn = await client.send_text("What was Netflix exact revenue in Q3 2023 from their 10-K filing?")
    assert "Sources:" in turn.text or any(phrase in turn.text.lower() for phrase in ["don't have", "not available", "cannot find", "no information"])


@pytest.mark.asyncio
async def test_out_of_scope_question_redirected() -> None:
    async with WebSocketClient("eval_neg_scope_001") as client:
        turn = await client.send_text("What is the recipe for chocolate cake?")
    assert not any(word in turn.text.lower() for word in ["flour", "sugar", "butter", "bake", "oven"])
