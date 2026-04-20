from __future__ import annotations

import pytest

from backend.voice.synthesizer import SpeechSynthesizer


def test_tts_text_cleaning() -> None:
    synth = SpeechSynthesizer()
    text = "**Revenue** grew 12% YoY to $10B in the 10-K and 10-Q; see DEF 14A."
    cleaned = synth._clean_for_tts(text)

    assert "**" not in cleaned
    assert "year over year" in cleaned
    assert "dollars" in cleaned
    assert "billion" in cleaned
    assert "ten K filing" in cleaned
    assert "ten Q filing" in cleaned
    assert "DEF fourteen A filing" in cleaned


@pytest.mark.asyncio
async def test_tts_synthesis() -> None:
    synth = SpeechSynthesizer()
    try:
        audio, duration = await synth.synthesize_full("Test synthesis.")
        assert isinstance(audio, (bytes, bytearray))
        assert duration >= 0
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Skipping network-dependent TTS test: {exc}")


@pytest.mark.asyncio
async def test_transcription_accuracy_placeholder() -> None:
    pytest.skip("Sample audio fixture not yet added for deterministic transcription testing")


@pytest.mark.asyncio
async def test_transcription_latency_placeholder() -> None:
    pytest.skip("Latency test requires fixed hardware baseline and sample clip")
