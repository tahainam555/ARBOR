from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvalConfig(BaseSettings):
    """Configuration for the evaluation suite."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    BASE_URL: str = Field(default="http://localhost:8000")
    WS_URL: str = Field(default="ws://localhost:8000/ws")

    ANTHROPIC_API_KEY: str = Field(default="")
    JUDGE_MODEL: str = Field(default="claude-sonnet-4-20250514")

    TOP_K: int = Field(default=5)
    PRECISION_AT_K_THRESHOLD: float = Field(default=0.70)
    FAITHFULNESS_THRESHOLD: float = Field(default=0.80)
    CONTEXT_RELEVANCE_THRESHOLD: float = Field(default=0.65)
    ANSWER_CORRECTNESS_THRESHOLD: float = Field(default=0.75)

    TOOL_INVOCATION_ACCURACY_THRESHOLD: float = Field(default=0.85)
    TOOL_ARGUMENT_ACCURACY_THRESHOLD: float = Field(default=0.80)

    ENTITY_EXTRACTION_ACCURACY_THRESHOLD: float = Field(default=0.90)

    STT_WER_THRESHOLD: float = Field(default=0.10)
    STT_LATENCY_MAX_MS: float = Field(default=500.0)
    FIRST_AUDIO_LATENCY_MAX_MS: float = Field(default=3000.0)

    TTFT_SIMPLE_MAX_MS: float = Field(default=2000.0)
    TTFT_RAG_MAX_MS: float = Field(default=3000.0)
    TTFT_TOOL_MAX_MS: float = Field(default=4000.0)
    TTFT_MIXED_MAX_MS: float = Field(default=5000.0)
    E2E_MAX_MS: float = Field(default=10000.0)

    MAX_CONCURRENT_USERS: int = Field(default=20)
    TURNS_PER_USER: int = Field(default=3)
    ACCEPTABLE_MEDIAN_TTFT_MS: float = Field(default=2000.0)

    RAG_EVAL_QUERIES: int = Field(default=30)
    LATENCY_TRIALS: int = Field(default=30)
    TOOL_TEST_UTTERANCES: int = Field(default=20)
    CONVERSATION_DIALOGUES: int = Field(default=10)

    @property
    def root_dir(self) -> Path:
        return Path(__file__).resolve().parent

    @property
    def workspace_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "data"

    @property
    def report_dir(self) -> Path:
        return self.workspace_root / "report"


@lru_cache(maxsize=1)
def get_config() -> EvalConfig:
    return EvalConfig()


config = get_config()
