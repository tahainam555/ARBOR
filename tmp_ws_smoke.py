from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import wave

import websockets

WS_URL = "ws://127.0.0.1:8000/ws/smoke-session"


def make_wav_tone(seconds: float = 0.8, sample_rate: int = 16000) -> bytes:
    """Create a short mono PCM WAV tone for websocket audio smoke tests."""
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
    """Receive server messages until turn_complete or error."""
    message_types: list[str] = []
    text_chunks: list[str] = []
    last_payload: dict = {}

    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=180)
        payload = json.loads(raw)
        last_payload = payload

        msg_type = payload.get("type", "")
        message_types.append(msg_type)

        if msg_type == "text_chunk":
            text_chunks.append(payload.get("content", ""))

        if msg_type in {"turn_complete", "error"}:
            break

    return message_types, "".join(text_chunks).strip(), last_payload


async def main() -> None:
    async with websockets.connect(WS_URL, max_size=None, ping_interval=None) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "text_input",
                    "message": "Say hello in one short sentence.",
                }
            )
        )
        text_types, text_reply, text_tail = await receive_turn(ws)

        print("TEXT_TYPES", text_types)
        print("TEXT_HAS_AUDIO", "audio_chunk" in text_types)
        print("TEXT_REPLY_LEN", len(text_reply))
        print("TEXT_TURN_COMPLETE", text_tail.get("type") == "turn_complete")

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

        print("AUDIO_TYPES", audio_types)
        print("AUDIO_HAS_TRANSCRIPTION", "transcription" in audio_types)
        print("AUDIO_HAS_AUDIO", "audio_chunk" in audio_types)
        print("AUDIO_REPLY_LEN", len(audio_reply))
        print("AUDIO_TURN_COMPLETE", audio_tail.get("type") == "turn_complete")


if __name__ == "__main__":
    asyncio.run(main())
