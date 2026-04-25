from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.chat_store import ChatStore
from backend.conversation_manager import ConversationManager
from backend.domain_classifier import DomainClassifier
from backend.latency_tracker import LatencyTracker
from backend.session_store import SessionStore


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_json(self, payload):
        self.messages.append(payload)


class StubLLM:
    async def generate_streaming(self, *args, **kwargs):
        raise AssertionError("LLM should not be called for off-domain requests")


class StubRetriever:
    async def _embed_query(self, *args, **kwargs):
        raise AssertionError("Retriever should not be called for off-domain requests")

    async def retrieve_with_embedding(self, *args, **kwargs):
        raise AssertionError("Retriever should not be called for off-domain requests")

    async def format_context(self, chunks):
        return ""


class StubTools:
    async def detect_and_execute(self, *args, **kwargs):
        raise AssertionError("Tools should not be called for off-domain requests")


class StubTranscriber:
    async def transcribe(self, *args, **kwargs):
        raise AssertionError("Transcriber should not be called")


class StubSynthesizer:
    async def synthesize_streaming(self, *args, **kwargs):
        raise AssertionError("Synthesizer should not be called")


class StubCRM:
    async def get_user(self, *args, **kwargs):
        return None

    async def log_interaction(self, *args, **kwargs):
        return True


class StubLatencyTracker:
    def __init__(self) -> None:
        self.logs: list[dict[str, object]] = []

    async def initialize(self) -> None:
        return None

    async def log(self, session_id, turn_id, stage, duration_ms, metadata=None):
        self.logs.append(
            {
                "session_id": session_id,
                "turn_id": turn_id,
                "stage": stage,
                "duration_ms": duration_ms,
                "metadata": metadata,
            }
        )

    async def get_turn_breakdown(self, session_id, turn_id):
        stages = {entry["stage"]: entry["duration_ms"] for entry in self.logs if entry["session_id"] == session_id and entry["turn_id"] == turn_id}
        return {"session_id": session_id, "turn_id": turn_id, "stages": stages}


@pytest.mark.asyncio
async def test_off_domain_turn_short_circuits(tmp_path: Path) -> None:
    db_path = tmp_path / "conversation.db"
    session_store = SessionStore(db_path=str(db_path))
    chat_store = ChatStore(db_path=str(db_path))
    await session_store.initialize()
    await chat_store.initialize()

    manager = ConversationManager(
        llm_engine=StubLLM(),
        retriever=StubRetriever(),
        tool_orchestrator=StubTools(),
        transcriber=StubTranscriber(),
        synthesizer=StubSynthesizer(),
        latency_tracker=StubLatencyTracker(),
        crm_tool=StubCRM(),
        session_store=session_store,
        chat_store=chat_store,
        domain_classifier=DomainClassifier(),
    )

    websocket = FakeWebSocket()
    breakdown = await manager.handle_text_turn(
        session_id="session-off-topic",
        message="Tell me a joke about the weather.",
        websocket=websocket,
    )

    assert breakdown["stages"]["domain_check"] >= 0
    assert websocket.messages[0]["type"] == "text_chunk"
    assert "only help with SEC filings" in str(websocket.messages[0]["content"])

    history = await chat_store.get_history("session-off-topic", limit=10)
    assert len(history) == 2
    assert history[1]["role"] == "assistant"
