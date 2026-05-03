from __future__ import annotations

import asyncio
from pathlib import Path

from backend.voice.synthesizer import SpeechSynthesizer

from evals.config import config

VOICE_TEST_SENTENCES = [
    "What was Apple total revenue in fiscal year 2023",
    "What is Tesla trading at right now",
    "My name is Ahmed and I am a conservative investor",
    "Calculate my ROI if I bought at 150 dollars and it is now at 248 dollars",
    "What are the latest news about Nvidia",
    "Compare Microsoft and Apple revenue growth over the last three years",
    "Add JPMorgan to my watchlist",
    "What were Exxon Mobil net earnings in 2022",
    "Show me the PE ratio for Walmart",
    "What is my current investment profile",
]


async def generate_audio_samples(output_dir: Path | None = None) -> list[Path]:
    output_dir = output_dir or (config.data_dir / "audio_samples")
    output_dir.mkdir(parents=True, exist_ok=True)

    synthesizer = SpeechSynthesizer()
    written: list[Path] = []
    for index, sentence in enumerate(VOICE_TEST_SENTENCES, start=1):
        audio_bytes, _ = await synthesizer.synthesize_full(sentence)
        ext = ".wav" if synthesizer.tts_backend == "local" else ".mp3"
        path = output_dir / f"sample_{index:02d}{ext}"
        path.write_bytes(audio_bytes)
        written.append(path)
    return written


if __name__ == "__main__":
    asyncio.run(generate_audio_samples())
