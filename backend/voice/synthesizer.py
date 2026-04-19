"""Text-to-speech wrapper around edge-tts with streaming audio chunks."""

from __future__ import annotations

import base64
import re
import time
from typing import Any

import edge_tts

from backend.config import get_settings


class SpeechSynthesizer:
    """Synthesizes assistant responses to speech with streaming support."""

    def __init__(self) -> None:
        self.voice = get_settings().tts_voice

    @staticmethod
    def _clean_for_tts(text: str) -> str:
        """Normalize markdown/finance tokens into speech-friendly text."""
        cleaned = text
        cleaned = re.sub(r"[`*_#]", "", cleaned)
        cleaned = cleaned.replace("10-K", "ten K filing")
        cleaned = cleaned.replace("YoY", "year over year")
        cleaned = re.sub(r"\$", " dollars ", cleaned)
        cleaned = re.sub(r"%", " percent ", cleaned)
        cleaned = re.sub(r"\b(\d+(?:\.\d+)?)B\b", r"\1 billion", cleaned)
        cleaned = re.sub(r"\b(\d+(?:\.\d+)?)M\b", r"\1 million", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentence-like chunks for lower-latency streaming."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in sentences if s.strip()]

    async def synthesize_streaming(self, text: str, websocket: Any, turn_id: int | None = None) -> float:
        """Stream sentence-level TTS chunks over websocket and return latency."""
        start = time.perf_counter()
        prepared = self._clean_for_tts(text)
        sentences = self._split_sentences(prepared)

        for sentence_index, sentence in enumerate(sentences):
            communicate = edge_tts.Communicate(sentence, self.voice)
            async for chunk in communicate.stream():
                if chunk["type"] != "audio":
                    continue

                encoded = base64.b64encode(chunk["data"]).decode("ascii")
                payload = {
                    "type": "audio_chunk",
                    "audio": encoded,
                    "sentence_index": sentence_index,
                }
                if turn_id is not None:
                    payload["turn_id"] = turn_id
                await websocket.send_json(payload)

        return (time.perf_counter() - start) * 1000.0

    async def synthesize_full(self, text: str) -> tuple[bytes, float]:
        """Synthesize full response text into one audio blob."""
        start = time.perf_counter()
        prepared = self._clean_for_tts(text)

        communicate = edge_tts.Communicate(prepared, self.voice)
        output = bytearray()

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                output.extend(chunk["data"])

        return bytes(output), (time.perf_counter() - start) * 1000.0
