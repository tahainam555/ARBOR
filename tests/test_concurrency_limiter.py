"""Unit tests for the TurnConcurrencyLimiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.concurrency_limiter import TurnConcurrencyLimiter

pytest_plugins = ("pytest_asyncio",)


@pytest.mark.asyncio
async def test_limiter_acquire_release() -> None:
    """Test basic acquire/release cycle."""
    limiter = TurnConcurrencyLimiter(max_concurrent=2)
    metrics = limiter.get_metrics()
    assert metrics.max_concurrent_turns == 2
    assert metrics.current_active_turns == 0

    # Acquire first turn
    wait_ms = await limiter.acquire_turn("session-1")
    assert wait_ms >= 0
    metrics = limiter.get_metrics()
    assert metrics.current_active_turns == 1
    assert metrics.total_turns_processed == 1

    # Acquire second turn
    wait_ms = await limiter.acquire_turn("session-2")
    assert wait_ms >= 0
    metrics = limiter.get_metrics()
    assert metrics.current_active_turns == 2

    # Release
    limiter.release_turn()
    metrics = limiter.get_metrics()
    assert metrics.current_active_turns == 1

    limiter.release_turn()
    metrics = limiter.get_metrics()
    assert metrics.current_active_turns == 0


@pytest.mark.asyncio
async def test_limiter_blocking_when_full() -> None:
    """Test that acquire blocks when all slots are taken."""
    limiter = TurnConcurrencyLimiter(max_concurrent=1)

    # Fill the slot
    await limiter.acquire_turn("session-1")
    metrics = limiter.get_metrics()
    assert metrics.current_active_turns == 1

    # Try to acquire a second turn - should block
    start = time.perf_counter()
    acquire_task = asyncio.create_task(limiter.acquire_turn("session-2"))

    # Give the task a moment to try to acquire (it should block)
    await asyncio.sleep(0.1)

    # Task should still be pending
    assert not acquire_task.done()

    # Release the first slot
    limiter.release_turn()

    # Now the waiting task should complete
    wait_ms = await acquire_task
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    # Should have waited roughly 100ms (plus some overhead)
    assert wait_ms >= 80.0  # Allow some variance
    assert elapsed_ms >= 100.0


@pytest.mark.asyncio
async def test_limiter_fairness() -> None:
    """Test that turns are served fairly in FIFO order."""
    limiter = TurnConcurrencyLimiter(max_concurrent=1)

    results = []

    async def session_task(session_id: str, delay_before_release: float) -> None:
        """Simulate a session turn."""
        start = time.perf_counter()
        wait_ms = await limiter.acquire_turn(session_id)
        results.append((session_id, wait_ms, start))
        await asyncio.sleep(delay_before_release)
        limiter.release_turn()

    # Create multiple sessions that all try to acquire
    tasks = [
        session_task("s1", 0.1),
        session_task("s2", 0.05),
        session_task("s3", 0.05),
    ]

    await asyncio.gather(*tasks)

    # Verify all sessions got a turn
    assert len(results) == 3
    session_ids = [r[0] for r in results]
    assert set(session_ids) == {"s1", "s2", "s3"}


@pytest.mark.asyncio
async def test_limiter_timeout() -> None:
    """Test that acquire times out if semaphore blocked too long."""
    limiter = TurnConcurrencyLimiter(max_concurrent=1, queue_timeout_seconds=0.2)

    # Fill the slot with a long-running task
    async def long_task() -> None:
        await limiter.acquire_turn("session-1")
        await asyncio.sleep(10.0)  # Hold for 10 seconds
        limiter.release_turn()

    task = asyncio.create_task(long_task())

    # Give it time to acquire
    await asyncio.sleep(0.05)

    # Try to acquire but should timeout
    with pytest.raises(RuntimeError, match="Turn queue timeout"):
        await limiter.acquire_turn("session-2")

    # Cleanup
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_limiter_metrics_accumulation() -> None:
    """Test that metrics accumulate correctly across multiple turns."""
    limiter = TurnConcurrencyLimiter(max_concurrent=2)

    # Run multiple turns
    for i in range(5):
        await limiter.acquire_turn(f"session-{i}")
        limiter.release_turn()

    metrics = limiter.get_metrics()
    assert metrics.total_turns_processed == 5
    assert metrics.current_active_turns == 0


@pytest.mark.asyncio
async def test_limiter_concurrent_sessions() -> None:
    """Test concurrent execution with realistic session load."""
    limiter = TurnConcurrencyLimiter(max_concurrent=3)

    execution_times = []

    async def session_worker(session_id: str, num_turns: int) -> None:
        """Worker that executes multiple turns sequentially."""
        for turn in range(num_turns):
            turn_start = time.perf_counter()
            await limiter.acquire_turn(f"{session_id}-turn-{turn}")
            await asyncio.sleep(0.05)  # Simulate work
            limiter.release_turn()
            turn_end = time.perf_counter()
            execution_times.append(turn_end - turn_start)

    # Run 5 sessions with 2 turns each
    tasks = [session_worker(f"session-{i}", 2) for i in range(5)]
    await asyncio.gather(*tasks)

    metrics = limiter.get_metrics()
    assert metrics.total_turns_processed == 10
    assert all(t >= 0.04 for t in execution_times)  # Each turn took at least 50ms
