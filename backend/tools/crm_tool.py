"""SQLite-backed CRM tool for user profile and interaction memory."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import aiosqlite

from backend.config import get_settings
from backend.tools.base_tool import BaseTool, ToolResult


ALLOWED_UPDATE_FIELDS = {
    "name",
    "email",
    "risk_profile",
    "investment_goals",
    "watchlist",
    "portfolio",
}


class CRMTool(BaseTool):
    """CRUD operations for user CRM state in SQLite."""

    name = "crm_tool"
    description = "Manage user profile, watchlist, and interaction history."
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "get_user",
                    "create_user",
                    "update_field",
                    "add_to_watchlist",
                    "log_interaction",
                    "get_interaction_history",
                ],
            },
            "user_id": {"type": "string"},
            "name": {"type": "string"},
            "field": {"type": "string"},
            "value": {},
            "ticker": {"type": "string"},
            "session_id": {"type": "string"},
            "summary": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["action", "user_id"],
        "additionalProperties": True,
    }

    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        self.db_path = str(Path(db_path) if db_path else settings.crm_db_path)

    async def initialize(self) -> None:
        """Initialize CRM database tables if absent."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                  user_id TEXT PRIMARY KEY,
                  name TEXT,
                  email TEXT,
                  risk_profile TEXT,
                  investment_goals TEXT,
                  watchlist TEXT,
                  portfolio TEXT,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS interactions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT,
                  session_id TEXT,
                  summary TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await conn.commit()

    @staticmethod
    def _deserialize_user(row: aiosqlite.Row | None) -> dict[str, Any] | None:
        """Convert a users table row into application dict format."""
        if row is None:
            return None

        investment_goals = json.loads(row[4]) if row[4] else []
        watchlist = json.loads(row[5]) if row[5] else []
        portfolio = json.loads(row[6]) if row[6] else {}

        return {
            "user_id": row[0],
            "name": row[1],
            "email": row[2],
            "risk_profile": row[3],
            "investment_goals": investment_goals,
            "watchlist": watchlist,
            "portfolio": portfolio,
            "created_at": row[7],
            "updated_at": row[8],
        }

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        """Fetch one user profile by user_id."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT user_id, name, email, risk_profile, investment_goals,
                       watchlist, portfolio, created_at, updated_at
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            )
            row = await cursor.fetchone()

        return self._deserialize_user(row)

    async def create_user(self, user_id: str, name: str) -> dict[str, Any]:
        """Create user if missing, then return stored profile."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT OR IGNORE INTO users
                (user_id, name, investment_goals, watchlist, portfolio)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, name, "[]", "[]", "{}"),
            )
            await conn.commit()

        user = await self.get_user(user_id)
        if user is None:
            raise RuntimeError("Failed to create user record")
        return user

    async def update_field(self, user_id: str, field: str, value: Any) -> bool:
        """Update one allowed user field."""
        if field not in ALLOWED_UPDATE_FIELDS:
            return False

        user = await self.get_user(user_id)
        if user is None:
            return False

        serialized_value: Any = value
        if field in {"investment_goals", "watchlist", "portfolio"}:
            serialized_value = json.dumps(value)

        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                f"""
                UPDATE users
                SET {field} = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (serialized_value, user_id),
            )
            await conn.commit()
        return True

    async def add_to_watchlist(self, user_id: str, ticker: str) -> bool:
        """Add ticker symbol to user watchlist without duplicates."""
        user = await self.get_user(user_id)
        if user is None:
            return False

        symbol = ticker.upper()
        watchlist = user.get("watchlist", [])
        if symbol not in watchlist:
            watchlist.append(symbol)

        return await self.update_field(user_id, "watchlist", watchlist)

    async def log_interaction(self, user_id: str, session_id: str, summary: str) -> bool:
        """Persist a compact interaction summary row."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO interactions (user_id, session_id, summary)
                VALUES (?, ?, ?)
                """,
                (user_id, session_id, summary),
            )
            await conn.commit()
        return True

    async def get_interaction_history(self, user_id: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return latest interaction summaries for a user."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT id, user_id, session_id, summary, timestamp
                FROM interactions
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            rows = await cursor.fetchall()

        return [
            {
                "id": row[0],
                "user_id": row[1],
                "session_id": row[2],
                "summary": row[3],
                "timestamp": row[4],
            }
            for row in rows
        ]

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Dispatch supported CRM actions."""
        start = time.perf_counter()
        action = kwargs.get("action")
        user_id = kwargs.get("user_id")

        try:
            if not action or not user_id:
                raise ValueError("action and user_id are required")

            if action == "get_user":
                user = await self.get_user(user_id)
                return ToolResult(
                    success=True,
                    data={"user": user},
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )

            if action == "create_user":
                name = kwargs.get("name") or "Investor"
                user = await self.create_user(user_id=user_id, name=name)
                return ToolResult(
                    success=True,
                    data={"user": user},
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )

            if action == "update_field":
                ok = await self.update_field(
                    user_id=user_id,
                    field=str(kwargs.get("field", "")),
                    value=kwargs.get("value"),
                )
                return ToolResult(
                    success=ok,
                    data={"updated": ok},
                    error=None if ok else "Field update failed",
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )

            if action == "add_to_watchlist":
                ticker = str(kwargs.get("ticker", "")).upper()
                ok = await self.add_to_watchlist(user_id=user_id, ticker=ticker)
                return ToolResult(
                    success=ok,
                    data={"added": ok, "ticker": ticker},
                    error=None if ok else "Watchlist update failed",
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )

            if action == "log_interaction":
                ok = await self.log_interaction(
                    user_id=user_id,
                    session_id=str(kwargs.get("session_id", "")),
                    summary=str(kwargs.get("summary", "")),
                )
                return ToolResult(
                    success=ok,
                    data={"logged": ok},
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )

            if action == "get_interaction_history":
                history = await self.get_interaction_history(
                    user_id=user_id,
                    limit=int(kwargs.get("limit", 5)),
                )
                return ToolResult(
                    success=True,
                    data={"history": history},
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )

            raise ValueError(f"Unsupported CRM action: {action}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                data={},
                error=str(exc),
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
