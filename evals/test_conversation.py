from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals._shared import read_json
from evals.harnesses.llm_judge import ConversationJudge
from evals.harnesses.websocket_client import WebSocketClient

DIALOGUES = read_json("conversation_dialogues.json")
JUDGE = ConversationJudge()


@pytest.mark.asyncio
async def test_all_dialogues_llm_judge() -> None:
    results = []

    for dialogue in DIALOGUES["dialogues"]:
        session_id = f"eval_conv_{dialogue['id']}"
        conversation: list[dict[str, str]] = []
        async with WebSocketClient(session_id) as client:
            for turn in dialogue["turns"]:
                turn_result = await client.send_text(turn["content"])
                conversation.append({"role": "user", "content": turn["content"]})
                conversation.append({"role": "assistant", "content": turn_result.text})

        judged = await JUDGE.score(dialogue, conversation)
        results.append(
            {
                "dialogue_id": dialogue["id"],
                "dialogue_name": dialogue["name"],
                "scores": judged.scores,
                "overall": judged.overall,
                "passed": judged.passed,
                "reasoning": judged.reasoning,
                "weaknesses": judged.weaknesses,
            }
        )

    average = sum(item["overall"] for item in results) / len(results)
    passing = sum(1 for item in results if item["passed"])
    (Path("report") / "conversation_quality_results.json").write_text(
        json.dumps({"average_overall_score": average, "dialogues_passed": passing, "dialogues_total": len(results), "per_dialogue": results}, indent=2),
        encoding="utf-8",
    )

    assert average >= 3.5 or passing >= 8
