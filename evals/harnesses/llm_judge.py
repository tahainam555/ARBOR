from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from evals.config import config


@dataclass
class JudgeResult:
    scores: dict[str, float]
    overall: float
    passed: bool
    reasoning: str
    weaknesses: list[str]


class ConversationJudge:
    """Claude-backed judge with a deterministic fallback."""

    def __init__(self) -> None:
        self.api_key = config.ANTHROPIC_API_KEY.strip()
        self.model = config.JUDGE_MODEL

    async def score(self, dialogue: dict[str, Any], conversation: list[dict[str, str]]) -> JudgeResult:
        if self.api_key:
            try:
                from anthropic import AsyncAnthropic

                client = AsyncAnthropic(api_key=self.api_key)
                prompt = self._build_prompt(dialogue, conversation)
                response = await client.messages.create(
                    model=self.model,
                    max_tokens=1000,
                    system=self._system_prompt(),
                    messages=[{"role": "user", "content": prompt}],
                )
                payload = json.loads(response.content[0].text)
                return self._normalize(payload)
            except Exception:
                pass

        return self._fallback_score(dialogue, conversation)

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are an expert evaluator for an SEC Investment Research AI assistant. "
            "Return only valid JSON." 
        )

    @staticmethod
    def _build_prompt(dialogue: dict[str, Any], conversation: list[dict[str, str]]) -> str:
        rubric = json.dumps(dialogue.get("rubric", {}), indent=2)
        conv = "\n".join(f"{item['role'].upper()}: {item['content']}" for item in conversation)
        return f"Dialogue: {dialogue.get('name', '')}\n\nRubric:\n{rubric}\n\nConversation:\n{conv}"

    @staticmethod
    def _normalize(payload: dict[str, Any]) -> JudgeResult:
        scores = {k: float(v) for k, v in payload.get("scores", {}).items()}
        overall = float(payload.get("overall", sum(scores.values()) / max(1, len(scores))))
        passed = bool(payload.get("passed", overall >= 3.5))
        reasoning = str(payload.get("reasoning", ""))
        weaknesses = [str(item) for item in payload.get("weaknesses", [])]
        return JudgeResult(scores=scores, overall=overall, passed=passed, reasoning=reasoning, weaknesses=weaknesses)

    @staticmethod
    def _fallback_score(dialogue: dict[str, Any], conversation: list[dict[str, str]]) -> JudgeResult:
        text = "\n".join(item["content"] for item in conversation).lower()
        rubric = dialogue.get("rubric", {})
        scores = {
            "task_completion": 4.0 if conversation else 1.0,
            "factual_accuracy": 3.5 if "source" in text or "according to" in text else 2.5,
            "memory_usage": 4.5 if any(keyword in text for keyword in ["my name is", "you said", "what is my name", "what kind of investor am i"]) else 3.0,
            "policy_adherence": 4.5 if "recipe" not in text and "capital of france" not in text else 2.0,
            "coherence": 4.0,
        }
        overall = sum(scores.values()) / len(scores)
        passed = overall >= 3.5 and scores["task_completion"] >= 3 and all(value > 1 for value in scores.values())
        reasoning = f"Fallback heuristic used for {dialogue.get('name', 'dialogue')}"
        weaknesses = [str(value) for key, value in rubric.items() if key not in {"task_completion", "factual_accuracy"}]
        return JudgeResult(scores=scores, overall=overall, passed=passed, reasoning=reasoning, weaknesses=weaknesses)
