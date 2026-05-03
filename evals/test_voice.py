from __future__ import annotations

import base64
import json
import statistics
import time
from pathlib import Path

import httpx
import pytest
from jiwer import wer

from evals._shared import DATA_DIR
from evals.config import config
from evals.harnesses.audio_generator import VOICE_TEST_SENTENCES, generate_audio_samples
from evals.harnesses.websocket_client import WebSocketClient


@pytest.fixture(scope="module", autouse=True)
def _ensure_audio_samples() -> None:
    import asyncio

    asyncio.run(generate_audio_samples())


@pytest.mark.asyncio
async def test_word_error_rate() -> None:
    sample_dir = DATA_DIR / "audio_samples"
    files = sorted(sample_dir.glob("sample_*.*"))
    references = VOICE_TEST_SENTENCES[: len(files)]
    scores = []

    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=120.0) as client:
        for reference, audio_path in zip(references, files):
            audio_bytes = audio_path.read_bytes()
            resp = await client.post(
                "/api/test/transcribe",
                json={"audio": base64.b64encode(audio_bytes).decode("ascii"), "format": audio_path.suffix.lstrip(".")},
            )
            resp.raise_for_status()
            hypothesis = resp.json()["transcription"]
            scores.append(wer(reference.lower(), hypothesis.lower()))

    average = sum(scores) / len(scores)
    (Path("report") / "voice_stt_results.json").write_text(json.dumps({"average_wer": average, "threshold": config.STT_WER_THRESHOLD, "passed": average < config.STT_WER_THRESHOLD}, indent=2), encoding="utf-8")
    assert average < config.STT_WER_THRESHOLD


@pytest.mark.asyncio
async def test_stt_latency_under_threshold() -> None:
    sample_dir = DATA_DIR / "audio_samples"
    files = sorted(sample_dir.glob("sample_*.*"))
    latencies = []
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=120.0) as client:
        for audio_path in files[:5]:
            start = time.perf_counter()
            resp = await client.post(
                "/api/test/transcribe",
                json={"audio": base64.b64encode(audio_path.read_bytes()).decode("ascii"), "format": audio_path.suffix.lstrip(".")},
            )
            resp.raise_for_status()
            latencies.append((time.perf_counter() - start) * 1000.0)
    assert statistics.mean(latencies) < config.STT_LATENCY_MAX_MS * 2


@pytest.mark.asyncio
async def test_tts_produces_audio_bytes() -> None:
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=120.0) as client:
        resp = await client.post("/api/test/synthesize", json={"text": "Apple revenue was 383 billion dollars in fiscal 2023"})
        resp.raise_for_status()
        data = resp.json()
        assert data["success"] is True
        assert len(data["audio_bytes_b64"]) > 100


@pytest.mark.asyncio
async def test_first_audio_latency() -> None:
    sample_dir = DATA_DIR / "audio_samples"
    audio_path = sorted(sample_dir.glob("sample_*.*"))[0]
    start = time.perf_counter()
    first_audio_ms = None
    async with WebSocketClient("eval_voice_latency_001") as client:
        result = await client.send_audio(audio_path.read_bytes(), audio_format=audio_path.suffix.lstrip("."))
        first_audio_ms = result.first_audio_ms
    assert first_audio_ms is not None
    assert first_audio_ms < config.FIRST_AUDIO_LATENCY_MAX_MS * 2
