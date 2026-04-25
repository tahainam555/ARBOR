from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from backend.chat_store import ChatStore
from backend.conversation_manager import ConversationManager
from backend.domain_classifier import DomainClassifier
from backend.session_store import SessionStore
from backend.summarizer import ConversationSummarizer


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.messages.append(payload)


class StubLLM:
    def __init__(self) -> None:
        self.last_prompt = ""

    async def generate_streaming(self, prompt: str, websocket: FakeWebSocket, **kwargs) -> str:  # type: ignore[override]
        del kwargs
        self.last_prompt = prompt
        await websocket.send_json({"type": "text_chunk", "content": "stub answer", "turn_id": 1})
        return "stub answer"


class StubRetriever:
    async def _embed_query(self, message: str) -> list[float]:
        del message
        return [0.1, 0.2]

    async def retrieve_with_embedding(self, query_embedding: list[float], top_k: int) -> list[dict[str, Any]]:
        del query_embedding, top_k
        return []

    async def format_context(self, chunks: list[dict[str, Any]]) -> str:
        del chunks
        return ""


class ToolResultStub:
    def __init__(self) -> None:
        self.results: dict[str, dict[str, Any]] = {}
        self.formatted_context = ""


class StubTools:
    async def detect_and_execute(self, message: str, session_id: str) -> ToolResultStub:
        del message, session_id
        return ToolResultStub()


class StubTranscriber:
    async def transcribe(self, audio_bytes: bytes, format_hint: str | None = None) -> tuple[str, float]:
        del audio_bytes, format_hint
        return "transcribed text", 10.0


class StubSynthesizer:
    async def synthesize_streaming(self, text: str, websocket: FakeWebSocket, turn_id: int) -> None:
        del text, websocket, turn_id
        return None


class StubCRM:
    async def get_user(self, user_id: str) -> None:
        del user_id
        return None

    async def log_interaction(self, user_id: str, session_id: str, summary: str) -> bool:
        del user_id, session_id, summary
        return True


class StubLatencyTracker:
    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []

    async def log(self, session_id: str, turn_id: int, stage: str, duration_ms: float, metadata: dict[str, Any] | None = None) -> None:
        self.logs.append(
            {
                "session_id": session_id,
                "turn_id": turn_id,
                "stage": stage,
                "duration_ms": duration_ms,
                "metadata": metadata,
            }
        )

    @asynccontextmanager
    async def measure(self, session_id: str, turn_id: int, stage: str, metadata: dict[str, Any] | None = None):
        del metadata
        yield
        await self.log(session_id=session_id, turn_id=turn_id, stage=stage, duration_ms=0.0)

    async def get_turn_breakdown(self, session_id: str, turn_id: int) -> dict[str, Any]:
        stages = {
            entry["stage"]: entry["duration_ms"]
            for entry in self.logs
            if entry["session_id"] == session_id and entry["turn_id"] == turn_id
        }
        return {"session_id": session_id, "turn_id": turn_id, "stages": stages}


def _build_manager(tmp_path: Path) -> tuple[ConversationManager, SessionStore, ChatStore, StubLLM]:
    db_path = tmp_path / "conversation.db"
    session_store = SessionStore(db_path=str(db_path))
    chat_store = ChatStore(db_path=str(db_path))
    llm = StubLLM()
    manager = ConversationManager(
        llm_engine=llm,
        retriever=StubRetriever(),
        tool_orchestrator=StubTools(),
        transcriber=StubTranscriber(),
        synthesizer=StubSynthesizer(),
        latency_tracker=StubLatencyTracker(),
        crm_tool=StubCRM(),
        session_store=session_store,
        chat_store=chat_store,
        domain_classifier=DomainClassifier(),
        summarizer=ConversationSummarizer(summary_interval_turns=4),
    )
    return manager, session_store, chat_store, llm


@pytest.mark.asyncio
async def test_manual_summary_refresh_updates_session(tmp_path: Path) -> None:
    manager, session_store, chat_store, _ = _build_manager(tmp_path)
    await session_store.initialize()
    await chat_store.initialize()
    await session_store.create_session("summary-session")

    await chat_store.append_message("summary-session", 1, "user", "Compare AAPL and MSFT revenue trends.")
    await chat_store.append_message("summary-session", 1, "assistant", "AAPL grew services while MSFT grew cloud.")

    payload = await manager.refresh_session_summary("summary-session")
    assert payload["summary"]
    assert "AAPL" in payload["summary"] or "MSFT" in payload["summary"]

    stored = await session_store.get_session("summary-session")
    assert stored is not None
    assert stored["summary"] == payload["summary"]


@pytest.mark.asyncio
async def test_prompt_includes_existing_session_summary(tmp_path: Path) -> None:
    manager, session_store, chat_store, llm = _build_manager(tmp_path)
    await session_store.initialize()
    await chat_store.initialize()
    await session_store.create_session("prompt-session")
    await session_store.update_summary("prompt-session", "Prior summary: user tracks AAPL cash flow.")

    ws = FakeWebSocket()
    await manager.handle_text_turn(
        session_id="prompt-session",
        message="What changed in the latest filing?",
        websocket=ws,
        speak_response=False,
    )

    assert "SESSION SUMMARY:" in llm.last_prompt
    assert "user tracks AAPL cash flow" in llm.last_prompt
