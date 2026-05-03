from __future__ import annotations

import json
import asyncio
from pathlib import Path

import httpx
import pytest

from evals._shared import read_json
from evals.config import config
from evals.harnesses.websocket_client import WebSocketClient

ENTITY_TESTS = read_json("entity_extraction_tests.json")


@pytest.mark.asyncio
async def test_entity_extraction_accuracy() -> None:
    passes = 0
    results = []
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        for test in ENTITY_TESTS["tests"]:
            resp = await client.post(
                "/api/test/entity_extract",
                json={"user_message": test["input"], "assistant_response": ""},
            )
            resp.raise_for_status()
            extracted = resp.json()["extracted"]
            expected = test["expected"]
            ok = _match_entities(extracted, expected)
            passes += int(ok)
            results.append({"input": test["input"], "passed": ok, "expected": expected, "got": extracted})

    accuracy = passes / len(ENTITY_TESTS["tests"])
    (Path("report") / "entity_extraction_results.json").write_text(json.dumps({"accuracy": accuracy, "results": results}, indent=2), encoding="utf-8")
    assert accuracy >= config.ENTITY_EXTRACTION_ACCURACY_THRESHOLD


@pytest.mark.asyncio
async def test_name_remembered_across_turns() -> None:
    async with WebSocketClient("eval_mem_name_001") as client:
        await client.send_text("My name is Evaluation User Alpha")
        await client.send_text("What was Apple revenue in 2023?")
        turn = await client.send_text("What is my name?")
    assert "Alpha" in turn.text or "Evaluation User" in turn.text


@pytest.mark.asyncio
async def test_risk_profile_remembered() -> None:
    async with WebSocketClient("eval_mem_risk_001") as client:
        await client.send_text("I am a very conservative investor")
        turn = await client.send_text("What kind of investor am I?")
    assert "conservative" in turn.text.lower()


@pytest.mark.asyncio
async def test_session_isolation() -> None:
    async def run(session_id: str, name: str) -> str:
        async with WebSocketClient(session_id) as client:
            await client.send_text(f"My name is {name}")
            turn = await client.send_text("What is my name?")
            return turn.text

    resp_a, resp_b = await asyncio.gather(
        run("eval_isolation_A_001", "AliceEvalUser"),
        run("eval_isolation_B_001", "BobEvalUser"),
    )
    assert "Alice" in resp_a and "Bob" in resp_b


@pytest.mark.asyncio
async def test_crm_persistence_after_reconnect() -> None:
    user_id = "eval_mem_persist_001"
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        await client.post("/api/crm/user", json={"user_id": user_id, "name": "Persisted Eval User"})
        resp = await client.get(f"/api/crm/user/{user_id}")
        resp.raise_for_status()
        assert resp.json()["name"] == "Persisted Eval User"


def _match_entities(extracted: dict, expected: dict) -> bool:
    if not expected:
        return extracted == {} or not extracted
    for key, val in expected.items():
        if key not in extracted:
            return False
        if isinstance(val, list):
            if not all(item in extracted[key] for item in val):
                return False
        elif isinstance(val, str):
            if str(extracted[key]).lower() != val.lower():
                return False
        else:
            if extracted[key] != val:
                return False
    return True
