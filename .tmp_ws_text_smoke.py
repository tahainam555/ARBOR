import asyncio
import json
import websockets

async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws/smoke-text"
    async with websockets.connect(uri, max_size=None) as ws:
        await ws.send(json.dumps({"type": "text_input", "message": "What was Apple's total revenue in fiscal year 2023?"}))
        chunks = []
        latency = {}
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            msg_type = msg.get("type")
            if msg_type == "text_chunk":
                chunks.append(msg.get("content", ""))
            elif msg_type == "error":
                print("SERVER_ERROR", msg.get("message", "unknown error"))
            elif msg_type == "turn_complete":
                latency = msg.get("latency_breakdown", {})
                break

        print("ASSISTANT_TEXT_START")
        print("".join(chunks).strip())
        print("ASSISTANT_TEXT_END")
        print("LATENCY_BREAKDOWN", json.dumps(latency, ensure_ascii=True))

asyncio.run(main())
