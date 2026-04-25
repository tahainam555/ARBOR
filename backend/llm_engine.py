"""Ollama engine wrapper with streaming token output."""

from __future__ import annotations

import asyncio
import json
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

    def _trim_prompt_to_context(self, prompt: str, reserved_output_tokens: int = 512) -> str:
        """Ensure prompt stays within the requested context window."""
        max_prompt_tokens = max(256, self.settings.n_ctx - reserved_output_tokens)
        prompt_words = prompt.split()
        if len(prompt_words) <= int(max_prompt_tokens / 1.3):
            return prompt

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
            prompt = self._trim_prompt_to_context(prompt, reserved_output_tokens=512)
            full_tokens: list[str] = []
            start_time = time.perf_counter()
            first_token_time: float | None = None

            async for token in self._stream_generate(prompt, temperature=0.1, max_tokens=512):
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
        async with self._model_lock:
            prompt = self._trim_prompt_to_context(prompt, reserved_output_tokens=100)
            return await self._generate_full_text(prompt, temperature=0.0, max_tokens=100)

    async def warmup(self) -> None:
        """Run a minimal completion once so first user turn has lower cold-start latency."""
        async with self._model_lock:
            await self._generate_full_text("Warmup.", temperature=0.0, max_tokens=1)
