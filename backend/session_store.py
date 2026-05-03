"""SQLite-backed storage for conversation sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from backend.config import get_settings


class SessionStore:
    """Persist conversation session metadata in SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        self.db_path = str(Path(db_path) if db_path else settings.conversation_db_path)

    async def initialize(self) -> None:
        """Create the sessions table if it does not exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  session_id TEXT PRIMARY KEY,
                  user_id TEXT,
                  title TEXT,
                  turn_count INTEGER NOT NULL DEFAULT 0,
                  summary TEXT,
                  summary_updated_at TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  last_activity TEXT NOT NULL
                )
                """
            )
            cursor = await conn.execute("PRAGMA table_info(sessions)")
            columns = {row[1] for row in await cursor.fetchall()}
            if "summary" not in columns:
                await conn.execute("ALTER TABLE sessions ADD COLUMN summary TEXT")
            if "summary_updated_at" not in columns:
                await conn.execute("ALTER TABLE sessions ADD COLUMN summary_updated_at TEXT")
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_last_activity
                ON sessions(last_activity)
                """
            )
            await conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _deserialize(row: aiosqlite.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None

        return {
            "session_id": row[0],
            "user_id": row[1],
            "title": row[2],
            "turn_count": int(row[3] or 0),
            "summary": row[4],
            "summary_updated_at": row[5],
            "created_at": row[6],
            "updated_at": row[7],
            "last_activity": row[8],
        }

    async def create_session(
        self,
        session_id: str,
        user_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Create a session row if missing and return the stored session."""
        now = self._now()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT OR IGNORE INTO sessions
                (session_id, user_id, title, turn_count, created_at, updated_at, last_activity)
                VALUES (?, ?, ?, 0, ?, ?, ?)
                """,
                (session_id, user_id, title, now, now, now),
            )
            await conn.commit()

        session = await self.get_session(session_id)
        if session is None:
            raise RuntimeError("Failed to create session record")
        return session

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Fetch one session by session_id."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT session_id, user_id, title, turn_count, summary, summary_updated_at,
                       created_at, updated_at, last_activity
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = await cursor.fetchone()

        return self._deserialize(row)

    async def touch_session(
        self,
        session_id: str,
        user_id: str | None = None,
        turn_count: int | None = None,
        title: str | None = None,
    ) -> None:
        """Update last activity and optionally turn count or user linkage."""
        now = self._now()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                UPDATE sessions
                SET
                  user_id = COALESCE(?, user_id),
                  title = COALESCE(?, title),
                  turn_count = COALESCE(?, turn_count),
                  updated_at = ?,
                  last_activity = ?
                WHERE session_id = ?
                """,
                (user_id, title, turn_count, now, now, session_id),
            )
            await conn.commit()

    async def list_sessions(self) -> list[dict[str, Any]]:
        """Return all sessions ordered by most recent activity."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT session_id, user_id, title, turn_count, summary, summary_updated_at,
                       created_at, updated_at, last_activity
                FROM sessions
                ORDER BY last_activity DESC, created_at DESC
                """
            )
            rows = await cursor.fetchall()

        return [session for row in rows if (session := self._deserialize(row)) is not None]

    async def delete_session(self, session_id: str) -> None:
        """Delete a session row."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            await conn.commit()

    async def update_summary(self, session_id: str, summary: str) -> None:
        """Persist running summary text for one session."""
        now = self._now()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                UPDATE sessions
                SET
                  summary = ?,
                  summary_updated_at = ?,
                  updated_at = ?,
                  last_activity = ?
                WHERE session_id = ?
                """,
                (summary, now, now, now, session_id),
            )
            await conn.commit()

    async def update_title(self, session_id: str, title: str) -> None:
        """Persist a concise human-readable title for one session."""
        now = self._now()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                UPDATE sessions
                SET title = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (title, now, session_id),
            )
            await conn.commit()
