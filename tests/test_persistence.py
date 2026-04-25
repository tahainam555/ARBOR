from __future__ import annotations

from pathlib import Path

import pytest

from backend.chat_store import ChatStore
from backend.session_store import SessionStore


@pytest.mark.asyncio
async def test_session_store_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "conversation.db"
    store = SessionStore(db_path=str(db_path))
    await store.initialize()

    created = await store.create_session("session-1", user_id="user-1", title="First Chat")
    assert created["session_id"] == "session-1"
    assert created["user_id"] == "user-1"

    await store.touch_session("session-1", turn_count=3)
    fetched = await store.get_session("session-1")
    assert fetched is not None
    assert fetched["turn_count"] == 3

    sessions = await store.list_sessions()
    assert sessions[0]["session_id"] == "session-1"
    assert sessions[0]["summary"] is None


@pytest.mark.asyncio
async def test_session_summary_persistence(tmp_path: Path) -> None:
    db_path = tmp_path / "conversation.db"
    store = SessionStore(db_path=str(db_path))
    await store.initialize()

    await store.create_session("session-3", user_id="user-3")
    await store.update_summary("session-3", "User prefers conservative portfolio updates.")

    session = await store.get_session("session-3")
    assert session is not None
    assert session["summary"] == "User prefers conservative portfolio updates."
    assert session["summary_updated_at"] is not None


@pytest.mark.asyncio
async def test_chat_store_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "conversation.db"
    session_store = SessionStore(db_path=str(db_path))
    chat_store = ChatStore(db_path=str(db_path))
    await session_store.initialize()
    await chat_store.initialize()

    await session_store.create_session("session-2")
    await chat_store.append_message("session-2", 1, "user", "What is AAPL trading at?")
    await chat_store.append_message("session-2", 1, "assistant", "AAPL is trading near $189.")
    await chat_store.append_message("session-2", 2, "user", "And MSFT?")

    history = await chat_store.get_history("session-2", limit=10)
    assert [message["role"] for message in history] == ["user", "assistant", "user"]
    assert history[1]["content"].startswith("AAPL is trading")

    turn_messages = await chat_store.get_turn_messages("session-2", 1)
    assert len(turn_messages) == 2
