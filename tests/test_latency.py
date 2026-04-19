from __future__ import annotations

from pathlib import Path

import pytest

from backend.latency_tracker import LatencyTracker


@pytest.mark.asyncio
async def test_latency_logging(tmp_path: Path) -> None:
    db_path = tmp_path / "latency.db"
    tracker = LatencyTracker(db_path=str(db_path))
    await tracker.initialize()

    await tracker.log("session-a", 1, "rag_retrieval", 88.2, {"chunks_retrieved": 5})

    breakdown = await tracker.get_turn_breakdown("session-a", 1)
    assert breakdown["session_id"] == "session-a"
    assert breakdown["turn_id"] == 1
    assert breakdown["stages"]["rag_retrieval"] == pytest.approx(88.2, rel=0.001)
    assert breakdown["records"][0]["metadata"]["chunks_retrieved"] == 5


@pytest.mark.asyncio
async def test_session_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "latency.db"
    tracker = LatencyTracker(db_path=str(db_path))
    await tracker.initialize()

    await tracker.log("session-b", 1, "rag_retrieval", 100.0)
    await tracker.log("session-b", 2, "rag_retrieval", 200.0)
    await tracker.log("session-b", 2, "llm_first_token", 500.0)

    summary = await tracker.get_session_summary("session-b")
    assert summary["rag_retrieval"] == pytest.approx(150.0, rel=0.001)
    assert summary["llm_first_token"] == pytest.approx(500.0, rel=0.001)


@pytest.mark.asyncio
async def test_global_averages(tmp_path: Path) -> None:
    db_path = tmp_path / "latency.db"
    tracker = LatencyTracker(db_path=str(db_path))
    await tracker.initialize()

    await tracker.log("session-1", 1, "tts_synthesis", 450.0)
    await tracker.log("session-2", 1, "tts_synthesis", 550.0)

    averages = await tracker.get_global_averages()
    assert averages["tts_synthesis"] == pytest.approx(500.0, rel=0.001)


@pytest.mark.asyncio
async def test_session_payload_shape(tmp_path: Path) -> None:
    db_path = tmp_path / "latency.db"
    tracker = LatencyTracker(db_path=str(db_path))
    await tracker.initialize()

    await tracker.log("session-c", 1, "stt_transcription", 300.0)
    await tracker.log("session-c", 1, "end_to_end", 2000.0)

    payload = await tracker.get_session_latency_payload("session-c")
    assert payload["session_id"] == "session-c"
    assert len(payload["turns"]) == 1
    assert payload["turns"][0]["stages"]["stt_transcription"] == pytest.approx(300.0, rel=0.001)
    assert payload["averages"]["end_to_end"] == pytest.approx(2000.0, rel=0.001)
