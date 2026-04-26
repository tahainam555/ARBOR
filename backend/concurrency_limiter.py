"""Concurrent turn execution limiter for multi-session load management."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class ConcurrencyMetrics:
    """Snapshot of concurrency limiter state."""

    max_concurrent_turns: int
    current_active_turns: int
    queued_sessions: int
    total_turns_processed: int
    total_wait_ms: float


class TurnConcurrencyLimiter:
    """Ensures at most N turns execute simultaneously across all sessions."""

    def __init__(self, max_concurrent: int = 4, queue_timeout_seconds: float = 5.0) -> None:
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent
        self.queue_timeout = queue_timeout_seconds
        self.total_turns = 0
        self.total_wait_ms = 0.0

    async def acquire_turn(self, session_id: str) -> float:
        """Block until a turn slot is available, return wait duration in ms."""
        start = time.perf_counter()
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=self.queue_timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(f"Turn queue timeout after {self.queue_timeout}s for session {session_id}")
        wait_ms = (time.perf_counter() - start) * 1000.0
        self.total_wait_ms += wait_ms
        self.total_turns += 1
        return wait_ms

    def release_turn(self) -> None:
        """Release one turn slot."""
        self.semaphore.release()

    def get_metrics(self) -> ConcurrencyMetrics:
        """Return current state snapshot."""
        active = self.max_concurrent - self.semaphore._value  # type: ignore[attr-defined]
        queued = 0
        if hasattr(self.semaphore, '_waiters') and self.semaphore._waiters:  # type: ignore[attr-defined]
            queued = len(self.semaphore._waiters)  # type: ignore[attr-defined]
        return ConcurrencyMetrics(
            max_concurrent_turns=self.max_concurrent,
            current_active_turns=active,
            queued_sessions=queued,
            total_turns_processed=self.total_turns,
            total_wait_ms=self.total_wait_ms,
        )
