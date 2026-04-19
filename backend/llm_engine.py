"""Llama.cpp engine wrapper with streaming token output."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from llama_cpp import Llama

from backend.config import get_settings


class LLMEngine:
    """Singleton wrapper around llama-cpp for streaming and short-form generation."""

    _instance: "LLMEngine | None" = None

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.model = Llama(
            model_path=str(settings.llm_model_file),
            n_ctx=settings.n_ctx,
            n_threads=settings.n_threads,
            n_batch=512,
            verbose=False,
            use_mmap=True,
            use_mlock=False,
        )

    @classmethod
    def get_instance(cls) -> "LLMEngine":
        """Return process-wide singleton model instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def generate_streaming(
        self,
        prompt: str,
        websocket: Any,
        session_id: str,
        turn_id: int,
        latency_tracker: Any,
    ) -> str:
        """Generate streamed text and emit websocket chunks token-by-token."""
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        full_tokens: list[str] = []
        start_time = time.perf_counter()
        first_token_time: float | None = None

        def worker() -> None:
            try:
                stream = self.model.create_completion(
                    prompt=prompt,
                    temperature=0.1,
                    top_p=0.9,
                    top_k=40,
                    repeat_penalty=1.1,
                    max_tokens=512,
                    stream=True,
                )

                for event in stream:
                    token = event["choices"][0]["text"]
                    loop.call_soon_threadsafe(queue.put_nowait, token)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        while True:
            token = await queue.get()
            if token is None:
                break

            if first_token_time is None:
                first_token_time = (time.perf_counter() - start_time) * 1000.0
                await latency_tracker.log(
                    session_id=session_id,
                    turn_id=turn_id,
                    stage="llm_first_token",
                    duration_ms=first_token_time,
                )

            full_tokens.append(token)
            await websocket.send_json(
                {
                    "type": "text_chunk",
                    "content": token,
                    "turn_id": turn_id,
                }
            )

        total_generation_ms = (time.perf_counter() - start_time) * 1000.0
        await latency_tracker.log(
            session_id=session_id,
            turn_id=turn_id,
            stage="llm_total_generation",
            duration_ms=total_generation_ms,
            metadata={"tokens": len(full_tokens)},
        )

        return "".join(full_tokens).strip()

    async def generate_full(self, prompt: str) -> str:
        """Generate a non-streaming short response for deterministic tool routing."""

        def run() -> str:
            result = self.model.create_completion(
                prompt=prompt,
                temperature=0.0,
                top_p=0.9,
                top_k=40,
                repeat_penalty=1.1,
                max_tokens=100,
                stream=False,
            )
            return result["choices"][0]["text"].strip()

        return await asyncio.to_thread(run)
