"""Ollama engine wrapper with streaming token output."""

from __future__ import annotations

import asyncio
<<<<<<< HEAD
import re
import threading
=======
import json
>>>>>>> ac7f852436c596021d363a069857b81fad70556e
import time
from typing import Any

import httpx

from backend.config import get_settings


class LLMEngine:
    """Singleton wrapper around Ollama for streaming and short-form generation."""

    _instance: "LLMEngine | None" = None

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self._model_lock = asyncio.Lock()
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model_name = settings.ollama_model
        self.request_timeout = httpx.Timeout(300.0, connect=30.0)

    @classmethod
    def get_instance(cls) -> "LLMEngine":
        """Return process-wide singleton model instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

<<<<<<< HEAD
    def _trim_prompt_to_context(self, prompt: str, reserved_output_tokens: int | None = None) -> str:
        """Ensure prompt fits context while preserving both instruction and latest user text."""
        if reserved_output_tokens is None:
            reserved_output_tokens = self.settings.llm_prompt_reserve_tokens
=======
    def _trim_prompt_to_context(self, prompt: str, reserved_output_tokens: int = 512) -> str:
        """Ensure prompt stays within the requested context window."""
>>>>>>> ac7f852436c596021d363a069857b81fad70556e
        max_prompt_tokens = max(256, self.settings.n_ctx - reserved_output_tokens)
        prompt_words = prompt.split()
        if len(prompt_words) <= int(max_prompt_tokens / 1.3):
            return prompt

<<<<<<< HEAD
        # Keep both the prompt prefix (system + retrieved context) and suffix (latest user turn).
        # This avoids dropping the RAG context when n_ctx is small.
        prefix_ratio = 0.6
        prefix_count = max(64, int(max_prompt_tokens * prefix_ratio))
        suffix_count = max_prompt_tokens - prefix_count
        if suffix_count < 64:
            suffix_count = 64
            prefix_count = max_prompt_tokens - suffix_count

        trimmed_tokens = prompt_tokens[:prefix_count] + prompt_tokens[-suffix_count:]
        trimmed = self.model.detokenize(trimmed_tokens).decode("utf-8", errors="ignore")
        return trimmed
=======
        return " ".join(prompt_words[-int(max_prompt_tokens / 1.3) :])

    def _request_payload(self, prompt: str, *, temperature: float, max_tokens: int) -> dict[str, Any]:
        """Build a request payload for Ollama's generate endpoint."""
        return {
            "model": self.model_name,
            "prompt": prompt,
            "raw": True,
            "stream": True,
            "keep_alive": "30m",
            "options": {
                "num_ctx": self.settings.n_ctx,
                "num_thread": self.settings.n_threads,
                "temperature": temperature,
                "top_p": 0.9,
                "top_k": 40,
                "repeat_penalty": 1.1,
                "num_predict": max_tokens,
            },
        }

    async def _stream_generate(self, prompt: str, temperature: float, max_tokens: int) -> asyncio.AsyncIterator[str]:
        """Stream response chunks from Ollama's generate API."""
        payload = self._request_payload(prompt, temperature=temperature, max_tokens=max_tokens)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.request_timeout) as client:
            async with client.stream("POST", "/api/generate", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue

                    chunk = json.loads(line)
                    text = str(chunk.get("response", ""))
                    if text:
                        yield text

                    if bool(chunk.get("done", False)):
                        break

    async def _generate_full_text(self, prompt: str, temperature: float, max_tokens: int) -> str:
        """Run a non-streaming Ollama generation request."""
        payload = self._request_payload(prompt, temperature=temperature, max_tokens=max_tokens)
        payload["stream"] = False

        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.request_timeout) as client:
            response = await client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            return str(data.get("response", "")).strip()
>>>>>>> ac7f852436c596021d363a069857b81fad70556e

    async def generate_streaming(
        self,
        prompt: str,
        websocket: Any,
        session_id: str,
        turn_id: int,
        latency_tracker: Any,
    ) -> str:
        """Generate streamed text and emit websocket chunks token-by-token."""
        async with self._model_lock:
<<<<<<< HEAD
            prompt = self._trim_prompt_to_context(prompt)
            queue: asyncio.Queue[str | None] = asyncio.Queue()
            loop = asyncio.get_running_loop()
=======
            prompt = self._trim_prompt_to_context(prompt, reserved_output_tokens=512)
>>>>>>> ac7f852436c596021d363a069857b81fad70556e
            full_tokens: list[str] = []
            start_time = time.perf_counter()
            first_token_time: float | None = None

<<<<<<< HEAD
            def worker() -> None:
                try:
                    stream = self.model.create_completion(
                        prompt=prompt,
                        temperature=0.1,
                        top_p=0.9,
                        top_k=40,
                        repeat_penalty=1.1,
                        max_tokens=self.settings.llm_stream_max_tokens,
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

=======
            async for token in self._stream_generate(prompt, temperature=0.1, max_tokens=512):
>>>>>>> ac7f852436c596021d363a069857b81fad70556e
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

    @staticmethod
    def _is_sentence_boundary(buffer: str) -> bool:
        cleaned = buffer.strip()
        if len(cleaned) < 20:
            return False
        if len(cleaned) >= 200:
            return True
        if re.search(r"[.!?](?:[\"')\]]|\s|$)", cleaned):
            return True
        if cleaned.endswith(":") or cleaned.endswith("..."):
            return True
        return False

    async def generate_sentence_streaming(
        self,
        prompt: str,
        sentence_queue: asyncio.Queue[str | None],
        websocket: Any,
        session_id: str,
        turn_id: int,
        latency_tracker: Any,
    ) -> str:
        """Stream tokens to the websocket and hand complete sentences to TTS."""
        async with self._model_lock:
            prompt = self._trim_prompt_to_context(prompt)
            loop = asyncio.get_running_loop()
            token_queue: asyncio.Queue[str | None] = asyncio.Queue()
            full_tokens: list[str] = []
            sentence_buffer = ""
            start_time = time.perf_counter()
            first_token_time: float | None = None

            def put_threadsafe(queue: asyncio.Queue[str | None], item: str | None) -> None:
                future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
                future.result()

            def worker() -> None:
                try:
                    stream = self.model.create_completion(
                        prompt=prompt,
                        temperature=0.1,
                        top_p=0.9,
                        top_k=40,
                        repeat_penalty=1.1,
                        max_tokens=self.settings.llm_stream_max_tokens,
                        stream=True,
                    )

                    for event in stream:
                        token = event["choices"][0]["text"]
                        put_threadsafe(token_queue, token)
                finally:
                    put_threadsafe(token_queue, None)

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()

            while True:
                token = await token_queue.get()
                if token is None:
                    break

                full_tokens.append(token)
                sentence_buffer += token

                if first_token_time is None and token.strip():
                    first_token_time = (time.perf_counter() - start_time) * 1000.0
                    await latency_tracker.log(
                        session_id=session_id,
                        turn_id=turn_id,
                        stage="llm_first_token",
                        duration_ms=first_token_time,
                    )

                await websocket.send_json(
                    {
                        "type": "text_chunk",
                        "content": token,
                        "turn_id": turn_id,
                    }
                )

                if self._is_sentence_boundary(sentence_buffer):
                    sentence = sentence_buffer.strip()
                    if sentence:
                        await sentence_queue.put(sentence)
                    sentence_buffer = ""

            if sentence_buffer.strip():
                await sentence_queue.put(sentence_buffer.strip())

            await sentence_queue.put(None)

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
<<<<<<< HEAD
        def run() -> str:
            result = self.model.create_completion(
                prompt=prompt,
                temperature=0.0,
                top_p=0.9,
                top_k=40,
                repeat_penalty=1.1,
                max_tokens=self.settings.llm_tool_max_tokens,
                stream=False,
            )
            return result["choices"][0]["text"].strip()

        async with self._model_lock:
            prompt = self._trim_prompt_to_context(prompt, reserved_output_tokens=self.settings.llm_tool_max_tokens + 48)
            return await asyncio.to_thread(run)
=======
        async with self._model_lock:
            prompt = self._trim_prompt_to_context(prompt, reserved_output_tokens=100)
            return await self._generate_full_text(prompt, temperature=0.0, max_tokens=100)
>>>>>>> ac7f852436c596021d363a069857b81fad70556e

    async def warmup(self) -> None:
        """Run a minimal completion once so first user turn has lower cold-start latency."""
        async with self._model_lock:
            await self._generate_full_text("Warmup.", temperature=0.0, max_tokens=1)
