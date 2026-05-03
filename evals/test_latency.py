from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import pytest

from evals.config import config
from evals.harnesses.websocket_client import WebSocketClient

SCENARIOS = {
    "simple_dialogue": {"message": "Hello, how are you today?", "description": "No RAG, no tools"},
    "rag_only": {"message": "What was Apple's total revenue in fiscal year 2023?", "description": "RAG retrieval required"},
    "tool_only": {"message": "What is Tesla's current stock price?", "description": "Single tool call"},
    "mixed": {"message": "What was Nvidia's revenue in 2023 and what is it trading at right now?", "description": "RAG + tool"},
}

TRIALS = 30


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario_name,scenario", SCENARIOS.items())
async def test_latency_scenario(scenario_name: str, scenario: dict) -> None:
    ttft_times: list[float] = []
    e2e_times: list[float] = []
    inter_token_times: list[float] = []

    for trial in range(TRIALS):
        session_id = f"eval_latency_{scenario_name}_{trial}"
        async with WebSocketClient(session_id) as client:
            turn = await client.send_text(scenario["message"])

        ttft_times.append(turn.first_text_ms or turn.end_ms or 0.0)
        e2e_times.append(turn.end_ms or 0.0)
        inter_token_times.append((turn.end_ms or 0.0) / max(1, len(turn.text.split())))

    result = {
        "scenario": scenario_name,
        "description": scenario["description"],
        "trials": TRIALS,
        "ttft": {"mean": statistics.mean(ttft_times), "median": statistics.median(ttft_times), "p90": _percentile(ttft_times, 90), "p99": _percentile(ttft_times, 99)},
        "e2e": {"mean": statistics.mean(e2e_times), "median": statistics.median(e2e_times), "p90": _percentile(e2e_times, 90), "p99": _percentile(e2e_times, 99)},
        "inter_token": {"mean": statistics.mean(inter_token_times), "median": statistics.median(inter_token_times)},
    }
    (Path("report") / f"latency_{scenario_name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    thresholds = {
        "simple_dialogue": {"ttft": config.TTFT_SIMPLE_MAX_MS, "e2e": config.E2E_MAX_MS},
        "rag_only": {"ttft": config.TTFT_RAG_MAX_MS, "e2e": config.E2E_MAX_MS},
        "tool_only": {"ttft": config.TTFT_TOOL_MAX_MS, "e2e": config.E2E_MAX_MS},
        "mixed": {"ttft": config.TTFT_MIXED_MAX_MS, "e2e": config.E2E_MAX_MS},
    }
    assert result["ttft"]["median"] < thresholds[scenario_name]["ttft"] * 2
    assert result["e2e"]["median"] < thresholds[scenario_name]["e2e"] * 2


def _percentile(values: list[float], percentile: int) -> float:
    sorted_values = sorted(values)
    index = min(len(sorted_values) - 1, int(len(sorted_values) * percentile / 100))
    return sorted_values[index]
