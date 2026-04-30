from __future__ import annotations

import pytest

from backend.conversation_manager import ConversationManager, ConversationSession, EntityMemoryExtractor, SessionManager
from backend.tools.crm_tool import CRMTool


def test_entity_memory_extraction() -> None:
    extractor = EntityMemoryExtractor()

    memory = extractor.extract(
        "My name is Sarah and I'm an aggressive investor. I'm watching NVDA and TSLA.",
        "Understood. I'll remember that Sarah prefers aggressive investing.",
        {},
    )

    assert memory["user_name"] == "Sarah"
    assert memory["risk_profile"] == "aggressive"
    assert set(memory["watchlist"]) == {"NVDA", "TSLA"}


@pytest.mark.asyncio
async def test_session_manager_isolation_and_crm_bootstrap(tmp_path) -> None:
    crm = CRMTool(db_path=str(tmp_path / "crm.db"))
    await crm.initialize()
    await crm.create_user("alice", "Alice")
    await crm.update_field("alice", "risk_profile", "moderate")
    await crm.add_to_watchlist("alice", "AAPL")

    manager = SessionManager(crm_tool=crm, max_sessions=100, session_timeout_minutes=30)
    session_a = await manager.get_or_create("session-a", user_id="alice")
    session_b = await manager.get_or_create("session-b", user_id="bob")

    assert session_a.entity_memory["user_name"] == "Alice"
    assert session_a.entity_memory["risk_profile"] == "moderate"
    assert "AAPL" in session_a.entity_memory["watchlist"]
    assert session_b.entity_memory == {}

    session_a.history.append({"role": "user", "content": "My name is Alice"})
    assert session_b.history == []


@pytest.mark.asyncio
async def test_prompt_contains_history_and_facts() -> None:
    manager = ConversationManager(
        llm_engine=object(),
        retriever=object(),
        tool_orchestrator=object(),
        transcriber=object(),
        synthesizer=object(),
        latency_tracker=object(),
        crm_tool=object(),
    )

    session = ConversationSession(
        session_id="s1",
        entity_memory={"user_name": "Sarah", "risk_profile": "aggressive"},
        history=[
            {"role": "user", "content": "My name is Sarah"},
            {"role": "assistant", "content": "Nice to meet you, Sarah."},
        ],
    )

    prompt = await manager._build_prompt(
        session=session,
        user_message="What is my name?",
        crm_context="No user profile loaded.",
        rag_context="[Source: AAPL 10-K 2023] Example",
        tool_context="",
    )

    assert "KNOWN USER FACTS" in prompt
    assert "Sarah" in prompt
    assert "<|start_header_id|>user<|end_header_id|>" in prompt
    assert "My name is Sarah" in prompt
