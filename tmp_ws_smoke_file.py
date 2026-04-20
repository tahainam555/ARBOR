from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import traceback
import wave
from pathlib import Path

import websockets

WS_URL = "ws://127.0.0.1:8000/ws/smoke-session-file"
RESULT_PATH = Path("tmp_ws_smoke_result.json")


def make_wav_tone(seconds: float = 0.8, sample_rate: int = 16000) -> bytes:
    frame_count = int(seconds * sample_rate)
    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        frames = bytearray()
        for i in range(frame_count):
            value = int(0.2 * 32767 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
            frames.extend(value.to_bytes(2, byteorder="little", signed=True))

        wav_file.writeframes(bytes(frames))

    return buffer.getvalue()


async def receive_turn(ws: websockets.WebSocketClientProtocol) -> tuple[list[str], str, dict]:
    types: list[str] = []
    text_chunks: list[str] = []
    tail: dict = {}

    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=180)
        payload = json.loads(raw)
        tail = payload

        msg_type = payload.get("type", "")
        types.append(msg_type)

        if msg_type == "text_chunk":
            text_chunks.append(payload.get("content", ""))

        if msg_type in {"turn_complete", "error"}:
            break

    return types, "".join(text_chunks).strip(), tail


async def run() -> dict:
    result: dict = {}

    async with websockets.connect(WS_URL, max_size=None, ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "text_input", "message": "Say hello in one short sentence."}))
        text_types, text_reply, text_tail = await receive_turn(ws)
        result["text"] = {
            "types": text_types,
            "has_audio_chunk": "audio_chunk" in text_types,
            "reply_len": len(text_reply),
            "done": text_tail.get("type") == "turn_complete",
        }

        audio_bytes = make_wav_tone()
        await ws.send(
            json.dumps(
                {
                    "type": "audio_input",
                    "audio": base64.b64encode(audio_bytes).decode("utf-8"),
                    "format": "wav",
                }
            )
        )
        audio_types, audio_reply, audio_tail = await receive_turn(ws)
        result["audio"] = {
            "types": audio_types,
            "has_transcription": "transcription" in audio_types,
            "has_audio_chunk": "audio_chunk" in audio_types,
            "reply_len": len(audio_reply),
            "done": audio_tail.get("type") == "turn_complete",
        }

    return result


def main() -> None:
    payload: dict
    try:
        payload = {"ok": True, "result": asyncio.run(run())}
    except Exception as exc:  # noqa: BLE001
        payload = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }

    RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
