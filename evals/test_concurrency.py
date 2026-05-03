from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path

from evals.config import config
from evals.harnesses.websocket_client import WebSocketClient

CONCURRENCY_LEVELS = [1, 2, 5, 10, 15, 20]
MESSAGES_PER_USER = [
    "What was Apple revenue in 2023?",
    "What is Tesla trading at right now?",
    "My name is load test user and I prefer low risk",
]


async def single_user_session(user_num: int, results: list) -> None:
    session_id = f"load_test_user_{user_num}_{int(time.time())}"
    turn_results = []
    try:
        async with WebSocketClient(session_id) as client:
            for message in MESSAGES_PER_USER:
                start = time.perf_counter()
                turn = await client.send_text(message)
                elapsed = (time.perf_counter() - start) * 1000.0
                turn_results.append({"ttft": elapsed, "e2e": elapsed, "error": False, "text": turn.text})
                await asyncio.sleep(0.2)
    except Exception as exc:
        turn_results.append({"error": True, "error_msg": str(exc)})
    results.append(turn_results)


async def run_concurrency_level(n_users: int) -> dict:
    results: list = []
    started = time.perf_counter()
    await asyncio.gather(*(single_user_session(i, results) for i in range(n_users)))
    wall_time = max(0.001, time.perf_counter() - started)

    all_turns = [turn for user in results for turn in user if not turn.get("error")]
    error_turns = [turn for user in results for turn in user if turn.get("error")]
    ttfts = [turn["ttft"] for turn in all_turns]
    e2es = [turn["e2e"] for turn in all_turns]

    acceptable = bool(ttfts and e2es and statistics.median(ttfts) < config.ACCEPTABLE_MEDIAN_TTFT_MS and statistics.median(e2es) < config.E2E_MAX_MS)
    return {
        "n_users": n_users,
        "total_turns": len(all_turns),
        "error_count": len(error_turns),
        "error_rate": len(error_turns) / max(1, len(all_turns) + len(error_turns)),
        "turns_per_second": len(all_turns) / wall_time,
        "ttft": {
            "median": statistics.median(ttfts) if ttfts else 0,
            "p90": _percentile(ttfts, 90) if ttfts else 0,
            "p99": _percentile(ttfts, 99) if ttfts else 0,
        },
        "e2e": {
            "median": statistics.median(e2es) if e2es else 0,
            "p90": _percentile(e2es, 90) if e2es else 0,
        },
        "acceptable": acceptable,
    }


async def run_full_load_test() -> dict:
    per_level = []
    breakpoint_found = None
    for level in CONCURRENCY_LEVELS:
        result = await run_concurrency_level(level)
        per_level.append(result)
        if not result["acceptable"] and breakpoint_found is None:
            breakpoint_found = level

    summary = {
        "max_sustainable_concurrency": max((item["n_users"] for item in per_level if item["acceptable"]), default=0),
        "breakpoint": breakpoint_found,
        "per_level": per_level,
    }
    Path("report").mkdir(exist_ok=True)
    (Path("report") / "concurrency_results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _percentile(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * percentile / 100))
    return ordered[index]


if __name__ == "__main__":
    asyncio.run(run_full_load_test())
