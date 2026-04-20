"""Speech-to-text wrapper around faster-whisper."""

from __future__ import annotations

import asyncio
import io
import logging
import time

import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio

from backend.config import get_settings


logger = logging.getLogger("sec-assistant")


class AudioTranscriber:
    """Singleton-style faster-whisper transcriber optimized for CPU."""

    _instance: "AudioTranscriber | None" = None

    def __init__(self) -> None:
        settings = get_settings()
        self.model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")

    @classmethod
    def get_instance(cls) -> "AudioTranscriber":
        """Return a shared transcriber model instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _resample_to_16k(signal: np.ndarray, sample_rate: int) -> np.ndarray:
        """Resample audio to 16kHz using linear interpolation."""
        if sample_rate == 16000:
            return signal.astype(np.float32)

        duration = signal.shape[0] / sample_rate
        target_len = max(1, int(duration * 16000))
        x_old = np.linspace(0.0, 1.0, signal.shape[0], endpoint=False)
        x_new = np.linspace(0.0, 1.0, target_len, endpoint=False)
        resampled = np.interp(x_new, x_old, signal)
        return resampled.astype(np.float32)

    @classmethod
    def _decode_audio_bytes(cls, audio_bytes: bytes, format_hint: str | None = None) -> np.ndarray:
        """Decode browser audio bytes into mono float32 waveform."""
        if not audio_bytes:
            return np.zeros((1,), dtype=np.float32)

        normalized_hint = (format_hint or "").strip().lower().lstrip(".")
        try_pyav_first = normalized_hint in {
            "",
            "webm",
            "ogg",
            "opus",
            "mp3",
            "m4a",
            "aac",
            "flac",
            "wav",
        }

        if try_pyav_first:
            try:
                decoded = decode_audio(io.BytesIO(audio_bytes), sampling_rate=16000)
                decoded = np.asarray(decoded, dtype=np.float32)

                if decoded.ndim > 1:
                    decoded = np.mean(decoded, axis=0).astype(np.float32)

                if decoded.size > 0:
                    return decoded
            except Exception as exc:  # noqa: BLE001
                logger.debug("PyAV audio decode failed, falling back to soundfile: %s", exc)

        data, sample_rate = sf.read(io.BytesIO(audio_bytes), dtype="float32", always_2d=False)

        if isinstance(data, np.ndarray) and data.ndim > 1:
            data = np.mean(data, axis=1)

        if not isinstance(data, np.ndarray):
            data = np.array(data, dtype=np.float32)

        if data.size == 0:
            return np.zeros((1,), dtype=np.float32)

        return cls._resample_to_16k(data.astype(np.float32), int(sample_rate))

    async def transcribe(self, audio_bytes: bytes, format_hint: str | None = None) -> tuple[str, float]:
        """Transcribe audio bytes and return transcript with latency in ms."""
        start = time.perf_counter()

        waveform = await asyncio.to_thread(self._decode_audio_bytes, audio_bytes, format_hint)

        def run_transcription() -> str:
            segments, _ = self.model.transcribe(
                waveform,
                beam_size=1,
                language="en",
                vad_filter=True,
                condition_on_previous_text=False,
            )
            return " ".join(segment.text.strip() for segment in segments).strip()

        text = await asyncio.to_thread(run_transcription)
        duration_ms = (time.perf_counter() - start) * 1000.0
        return text, duration_ms

    async def warmup(self) -> None:
        """Run a tiny silent inference once to lower first real transcription latency."""

        def run_warmup() -> None:
            silence = np.zeros((16000,), dtype=np.float32)
            segments, _ = self.model.transcribe(
                silence,
                beam_size=1,
                language="en",
                vad_filter=True,
                condition_on_previous_text=False,
            )
            for _ in segments:
                break

        await asyncio.to_thread(run_warmup)
