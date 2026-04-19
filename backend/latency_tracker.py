"""Latency measurement and reporting utilities."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

import aiosqlite

from backend.config import get_settings


@dataclass
class LatencyRecord:
    """Single latency record row."""

    session_id: str
    turn_id: int
    stage: str
    duration_ms: float
    metadata: dict[str, Any] | None


class LatencyTracker:
    """Persists stage-level latency measurements in SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        self.db_path = str(settings.latency_db_path if db_path is None else db_path)

    async def initialize(self) -> None:
        """Create required table if it does not exist."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS latency_logs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT NOT NULL,
                  turn_id INTEGER NOT NULL,
                  stage TEXT NOT NULL,
                  duration_ms REAL NOT NULL,
                  metadata TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await conn.commit()

    @asynccontextmanager
    async def measure(
        self,
        session_id: str,
        turn_id: int,
        stage: str,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[None]:
        """Measure execution time for a stage and persist it automatically."""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            await self.log(session_id, turn_id, stage, duration_ms, metadata)

    def start(
        self,
        session_id: str,
        turn_id: int,
        stage: str,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[None]:
        """Backward-compatible alias that returns the async measurement context manager."""
        return self.measure(session_id, turn_id, stage, metadata)

    async def log(
        self,
        session_id: str,
        turn_id: int,
        stage: str,
        duration_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write a single latency measurement."""
        metadata_str = json.dumps(metadata) if metadata is not None else None
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO latency_logs (session_id, turn_id, stage, duration_ms, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, turn_id, stage, duration_ms, metadata_str),
            )
            await conn.commit()

    async def get_session_summary(self, session_id: str) -> dict[str, float]:
        """Return average duration per stage for one session."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT stage, AVG(duration_ms)
                FROM latency_logs
                WHERE session_id = ?
                GROUP BY stage
                """,
                (session_id,),
            )
            rows = await cursor.fetchall()

        return {stage: round(avg, 3) for stage, avg in rows}

    async def get_global_averages(self) -> dict[str, float]:
        """Return average duration per stage across all sessions."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT stage, AVG(duration_ms)
                FROM latency_logs
                GROUP BY stage
                """
            )
            rows = await cursor.fetchall()

        return {stage: round(avg, 3) for stage, avg in rows}

    async def get_turn_breakdown(self, session_id: str, turn_id: int) -> dict[str, Any]:
        """Return full stage breakdown for one conversation turn."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT stage, duration_ms, metadata, timestamp
                FROM latency_logs
                WHERE session_id = ? AND turn_id = ?
                ORDER BY id ASC
                """,
                (session_id, turn_id),
            )
            rows = await cursor.fetchall()

        stages: dict[str, float] = {}
        records: list[dict[str, Any]] = []
        for stage, duration_ms, metadata, timestamp in rows:
            parsed_metadata = json.loads(metadata) if metadata else None
            stages[stage] = round(float(duration_ms), 3)
            records.append(
                {
                    "stage": stage,
                    "duration_ms": round(float(duration_ms), 3),
                    "metadata": parsed_metadata,
                    "timestamp": timestamp,
                }
            )

        return {
            "session_id": session_id,
            "turn_id": turn_id,
            "stages": stages,
            "records": records,
        }

    async def get_session_latency_payload(self, session_id: str) -> dict[str, Any]:
        """Build payload shape expected by the latency API endpoint."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT turn_id, stage, duration_ms
                FROM latency_logs
                WHERE session_id = ?
                ORDER BY turn_id ASC, id ASC
                """,
                (session_id,),
            )
            rows = await cursor.fetchall()

        turns_map: dict[int, dict[str, float]] = defaultdict(dict)
        for turn_id, stage, duration_ms in rows:
            turns_map[int(turn_id)][str(stage)] = round(float(duration_ms), 3)

        turns = [
            {"turn_id": turn_id, "stages": stages}
            for turn_id, stages in sorted(turns_map.items(), key=lambda item: item[0])
        ]

        averages = await self.get_session_summary(session_id)

        return {
            "session_id": session_id,
            "turns": turns,
            "averages": averages,
        }
