"""Text-to-speech wrapper with edge-tts and local fallback support."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import tempfile
import threading
import time
from typing import Any

import edge_tts

from backend.config import get_settings


logger = logging.getLogger("sec-assistant")

try:
    import pyttsx3
except Exception:  # pragma: no cover - optional dependency guard
    pyttsx3 = None


class SpeechSynthesizer:
    """Synthesizes assistant responses to speech with streaming support."""

    def __init__(self) -> None:
        settings = get_settings()
        self.voice = settings.tts_voice
        self.tts_backend = settings.tts_backend.lower()
        self._local_lock = threading.Lock()
        self._local_engine = self._init_local_engine() if self.tts_backend in {"auto", "local"} else None

    @staticmethod
    def _init_local_engine() -> Any | None:
        """Initialize local pyttsx3 engine if available."""
        if pyttsx3 is None:
            return None

        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 175)
            return engine
        except Exception:
            return None

    @staticmethod
    def _clean_for_tts(text: str) -> str:
        """Normalize markdown/finance tokens into speech-friendly text."""
        cleaned = text
        cleaned = re.sub(r"[`*_#]", "", cleaned)
        cleaned = cleaned.replace("DEF 14A/A", "DEF fourteen A amendment")
        cleaned = cleaned.replace("DEF 14A", "DEF fourteen A filing")
        cleaned = cleaned.replace("10-K", "ten K filing")
        cleaned = cleaned.replace("10-Q", "ten Q filing")
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

    async def _send_audio_chunk(
        self,
        websocket: Any,
        chunk_bytes: bytes,
        sentence_index: int,
        turn_id: int | None,
        mime_type: str,
        backend: str,
    ) -> None:
        """Encode and send one audio chunk over websocket."""
        encoded = base64.b64encode(chunk_bytes).decode("ascii")
        payload: dict[str, Any] = {
            "type": "audio_chunk",
            "audio": encoded,
            "sentence_index": sentence_index,
            "mime_type": mime_type,
            "tts_backend": backend,
        }
        if turn_id is not None:
            payload["turn_id"] = turn_id
        await websocket.send_json(payload)

    async def _stream_edge(self, prepared_text: str, websocket: Any, turn_id: int | None = None) -> None:
        """Stream TTS audio using edge-tts sentence by sentence."""
        sentences = self._split_sentences(prepared_text)
        if not sentences:
            return

        for sentence_index, sentence in enumerate(sentences):
            communicate = edge_tts.Communicate(sentence, self.voice)
            async for chunk in communicate.stream():
                if chunk["type"] != "audio":
                    continue

                await self._send_audio_chunk(
                    websocket=websocket,
                    chunk_bytes=chunk["data"],
                    sentence_index=sentence_index,
                    turn_id=turn_id,
                    mime_type="audio/mpeg",
                    backend="edge",
                )

    def _synthesize_local_wav_sync(self, prepared_text: str) -> bytes:
        """Generate local TTS waveform bytes synchronously via pyttsx3."""
        if self._local_engine is None:
            raise RuntimeError("Local TTS backend unavailable. Install pyttsx3 and ensure system voices are configured.")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            temp_path = temp_file.name

        try:
            with self._local_lock:
                self._local_engine.save_to_file(prepared_text, temp_path)
                self._local_engine.runAndWait()

            with open(temp_path, "rb") as file_obj:
                return file_obj.read()
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    async def _stream_local(self, prepared_text: str, websocket: Any, turn_id: int | None = None) -> None:
        """Stream locally synthesized WAV audio in fixed-size chunks."""
        audio_bytes = await asyncio.to_thread(self._synthesize_local_wav_sync, prepared_text)
        chunk_size = 32 * 1024

        for index, offset in enumerate(range(0, len(audio_bytes), chunk_size)):
            chunk = audio_bytes[offset : offset + chunk_size]
            await self._send_audio_chunk(
                websocket=websocket,
                chunk_bytes=chunk,
                sentence_index=index,
                turn_id=turn_id,
                mime_type="audio/wav",
                backend="local",
            )

    async def synthesize_streaming(self, text: str, websocket: Any, turn_id: int | None = None) -> float:
        """Stream sentence-level TTS chunks over websocket and return latency."""
        start = time.perf_counter()
        prepared = self._clean_for_tts(text)
        if not prepared:
            return (time.perf_counter() - start) * 1000.0

        if self.tts_backend == "edge":
            await self._stream_edge(prepared, websocket, turn_id=turn_id)
            return (time.perf_counter() - start) * 1000.0

        if self.tts_backend == "local":
            await self._stream_local(prepared, websocket, turn_id=turn_id)
            return (time.perf_counter() - start) * 1000.0

        try:
            await self._stream_edge(prepared, websocket, turn_id=turn_id)
        except Exception:
            await self._stream_local(prepared, websocket, turn_id=turn_id)

        return (time.perf_counter() - start) * 1000.0

    async def consume_and_stream(
        self,
        sentence_queue: asyncio.Queue,
        websocket: Any,
        turn_id: int,
        latency_tracker: Any,
        session_id: str,
    ) -> float:
        """Consume complete sentences from the queue and stream one audio blob per sentence."""
        sentence_index = 0
        total_tts_ms = 0.0
        tts_start = time.perf_counter()

        while True:
            sentence = await sentence_queue.get()
            if sentence is None:
                break

            clean = self._clean_for_tts(str(sentence))
            if not clean:
                continue

            synth_start = time.perf_counter()
            try:
                if self.tts_backend == "local":
                    audio_bytes = await asyncio.to_thread(self._synthesize_local_wav_sync, clean)
                    mime_type = "audio/wav"
                    backend = "local"
                elif self.tts_backend == "edge":
                    audio_bytes = await self._synthesize_edge_full(clean)
                    mime_type = "audio/mpeg"
                    backend = "edge"
                else:
                    try:
                        audio_bytes = await self._synthesize_edge_full(clean)
                        mime_type = "audio/mpeg"
                        backend = "edge"
                    except Exception:
                        audio_bytes = await asyncio.to_thread(self._synthesize_local_wav_sync, clean)
                        mime_type = "audio/wav"
                        backend = "local"

                total_tts_ms += (time.perf_counter() - synth_start) * 1000.0
                await self._send_audio_chunk(
                    websocket=websocket,
                    chunk_bytes=audio_bytes,
                    sentence_index=sentence_index,
                    turn_id=turn_id,
                    mime_type=mime_type,
                    backend=backend,
                )
                sentence_index += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("TTS failed for sentence %s: %s", sentence_index, exc)

        await websocket.send_json(
            {
                "type": "audio_complete",
                "turn_id": turn_id,
                "sentences_synthesized": sentence_index,
            }
        )

        wall_tts_ms = (time.perf_counter() - tts_start) * 1000.0
        await latency_tracker.log(
            session_id=session_id,
            turn_id=turn_id,
            stage="tts_synthesis",
            duration_ms=total_tts_ms,
            metadata={"sentences": sentence_index, "wall_ms": wall_tts_ms},
        )
        return total_tts_ms

    async def _synthesize_edge_full(self, prepared_text: str) -> bytes:
        """Synthesize full response using edge-tts."""
        communicate = edge_tts.Communicate(prepared_text, self.voice)
        output = bytearray()

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                output.extend(chunk["data"])

        return bytes(output)

    async def synthesize_full(self, text: str) -> tuple[bytes, float]:
        """Synthesize full response text into one audio blob."""
        start = time.perf_counter()
        prepared = self._clean_for_tts(text)
        if not prepared:
            return b"", (time.perf_counter() - start) * 1000.0

        if self.tts_backend == "edge":
            audio = await self._synthesize_edge_full(prepared)
            return audio, (time.perf_counter() - start) * 1000.0

        if self.tts_backend == "local":
            audio = await asyncio.to_thread(self._synthesize_local_wav_sync, prepared)
            return audio, (time.perf_counter() - start) * 1000.0

        try:
            audio = await self._synthesize_edge_full(prepared)
        except Exception:
            audio = await asyncio.to_thread(self._synthesize_local_wav_sync, prepared)

        return audio, (time.perf_counter() - start) * 1000.0
