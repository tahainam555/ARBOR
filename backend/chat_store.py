"""SQLite-backed storage for conversation messages."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from backend.config import get_settings


class ChatStore:
    """Persist turn-by-turn chat messages in SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        self.db_path = str(Path(db_path) if db_path else settings.conversation_db_path)

    async def initialize(self) -> None:
        """Create the chat and audio tables if they do not exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT NOT NULL,
                  turn_id INTEGER NOT NULL,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  created_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session_turn
                ON chat_messages(session_id, turn_id, id)
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS message_audio (
                  session_id TEXT NOT NULL,
                  turn_id INTEGER NOT NULL,
                  role TEXT NOT NULL,
                  mime_type TEXT NOT NULL,
                  audio_base64 TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  PRIMARY KEY (session_id, turn_id, role)
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_message_audio_session_turn
                ON message_audio(session_id, turn_id)
                """
            )
            await conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    async def append_message(self, session_id: str, turn_id: int, role: str, content: str) -> None:
        """Persist one message row."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO chat_messages (session_id, turn_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, turn_id, role, content, self._now()),
            )
            await conn.commit()

    async def save_message_audio(
        self,
        session_id: str,
        turn_id: int,
        role: str,
        audio_base64: str,
        mime_type: str,
    ) -> None:
        """Persist replayable audio for one turn message."""
        if not audio_base64:
            return

        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO message_audio
                (session_id, turn_id, role, mime_type, audio_base64, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, turn_id, role, mime_type, audio_base64, self._now()),
            )
            await conn.commit()

    async def get_history(self, session_id: str, limit: int = 12) -> list[dict[str, Any]]:
        """Return the latest messages for one session in chronological order."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT session_id, turn_id, role, content, created_at
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
            rows = await cursor.fetchall()

        messages = [
            {
                "session_id": row[0],
                "turn_id": int(row[1]),
                "role": row[2],
                "content": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]
        messages.reverse()
        await self._attach_audio(session_id, messages)
        return messages

    async def _attach_audio(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        """Attach replayable audio metadata to matching assistant messages."""
        if not messages:
            return

        turn_ids = sorted({int(message["turn_id"]) for message in messages})
        placeholders = ",".join("?" for _ in turn_ids)
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                f"""
                SELECT turn_id, role, mime_type, audio_base64
                FROM message_audio
                WHERE session_id = ? AND turn_id IN ({placeholders})
                """,
                (session_id, *turn_ids),
            )
            rows = await cursor.fetchall()

        audio_by_key = {
            (int(row[0]), row[1]): {"mime_type": row[2], "audio": row[3]}
            for row in rows
        }
        for message in messages:
            audio = audio_by_key.get((int(message["turn_id"]), message["role"]))
            if audio:
                message["audio"] = audio["audio"]
                message["mime_type"] = audio["mime_type"]

    async def get_turn_messages(self, session_id: str, turn_id: int) -> list[dict[str, Any]]:
        """Return all messages stored for one turn."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT session_id, turn_id, role, content, created_at
                FROM chat_messages
                WHERE session_id = ? AND turn_id = ?
                ORDER BY id ASC
                """,
                (session_id, turn_id),
            )
            rows = await cursor.fetchall()

        return [
            {
                "session_id": row[0],
                "turn_id": int(row[1]),
                "role": row[2],
                "content": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]

    async def delete_session_messages(self, session_id: str) -> None:
        """Delete every message associated with one session."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
            await conn.commit()
