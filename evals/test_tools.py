from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from evals._shared import read_json
from evals.config import config
from evals.harnesses.websocket_client import WebSocketClient

TOOL_TESTS = read_json("tool_invocation_tests.json")


@pytest.mark.asyncio
async def test_crm_tool_functional() -> None:
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        resp = await client.post("/api/crm/user", json={"user_id": "test_eval_001", "name": "Eval User"})
        resp.raise_for_status()
        assert resp.json()["user_id"] == "test_eval_001"

        resp = await client.get("/api/crm/user/test_eval_001")
        resp.raise_for_status()
        assert resp.json()["name"] == "Eval User"

        resp = await client.patch("/api/crm/user/test_eval_001", json={"field": "risk_profile", "value": "aggressive"})
        resp.raise_for_status()

        resp = await client.post("/api/crm/user/test_eval_001/watchlist", json={"ticker": "AAPL"})
        resp.raise_for_status()

        resp = await client.get("/api/crm/user/test_eval_001")
        resp.raise_for_status()
        assert "AAPL" in resp.json()["watchlist"]


@pytest.mark.asyncio
async def test_stock_price_tool_functional() -> None:
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        resp = await client.get("/api/tools/stock_price", params={"ticker": "AAPL"})
        resp.raise_for_status()
        data = resp.json()
        assert data["success"] is True
        assert data["ticker"] == "AAPL"
        assert data["price"] > 0


@pytest.mark.asyncio
async def test_calculator_tool_functional() -> None:
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        resp = await client.post(
            "/api/tools/calculator",
            json={"calculation_type": "roi", "params": {"cost_basis": 150.0, "current_value": 248.0}},
        )
        resp.raise_for_status()
        data = resp.json()
        assert data["success"] is True
        assert abs(float(data["result"]) - 65.3333) < 0.1


@pytest.mark.asyncio
async def test_news_tool_functional() -> None:
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        resp = await client.get("/api/tools/news", params={"query": "Microsoft", "max_results": 5})
        resp.raise_for_status()
        data = resp.json()
        assert data["success"] in {True, False}
        if data["success"]:
            assert isinstance(data.get("articles", []), list)


@pytest.mark.asyncio
async def test_llm_tool_invocation_accuracy() -> None:
    tool_correct = 0
    arg_correct = 0
    total = len(TOOL_TESTS["tests"])
    results = []

    for test in TOOL_TESTS["tests"]:
        session_id = f"eval_tool_{test['id']}"
        async with WebSocketClient(session_id) as client:
            turn = await client.send_text(test["utterance"])

        called = [tool_call["tool_name"] for tool_call in turn.tool_calls]
        expected = test.get("expected_tool")
        if expected is None:
            if not called:
                tool_correct += 1
        else:
            if expected in called:
                tool_correct += 1
                matching = next((item for item in turn.tool_calls if item["tool_name"] == expected), None)
                if matching and _args_match(matching.get("args", {}), test.get("expected_args", {})):
                    arg_correct += 1

        results.append({"id": test["id"], "expected": expected, "called": called})

    invocation_accuracy = tool_correct / max(1, total)
    argument_accuracy = arg_correct / max(1, tool_correct)
    (Path("report") / "tool_invocation_results.json").write_text(
        json.dumps(
            {
                "invocation_accuracy": invocation_accuracy,
                "argument_accuracy": argument_accuracy,
                "thresholds": {
                    "invocation": config.TOOL_INVOCATION_ACCURACY_THRESHOLD,
                    "arguments": config.TOOL_ARGUMENT_ACCURACY_THRESHOLD,
                },
                "per_test": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    assert invocation_accuracy >= config.TOOL_INVOCATION_ACCURACY_THRESHOLD
    assert argument_accuracy >= config.TOOL_ARGUMENT_ACCURACY_THRESHOLD


def _args_match(actual: dict, expected: dict, tolerance: float = 0.05) -> bool:
    for key, exp_val in expected.items():
        if key not in actual:
            return False
        act_val = actual[key]
        if isinstance(exp_val, (int, float)):
            try:
                if abs(float(act_val) - float(exp_val)) / max(abs(float(exp_val)), 1.0) > tolerance:
                    return False
            except Exception:
                return False
        elif isinstance(exp_val, str):
            if str(act_val).upper() != exp_val.upper():
                return False
        else:
            if act_val != exp_val:
                return False
    return True
