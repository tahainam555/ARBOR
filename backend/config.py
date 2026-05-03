"""Application configuration for the SEC Investment Assistant."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    llm_model_path: str = Field(
        default="./models/tiny-llama-miniguanaco-1.5t.q2_k.gguf",
        alias="LLM_MODEL_PATH",
    )
    n_threads: int = Field(default=4, alias="N_THREADS")
    n_ctx: int = Field(default=1024, alias="N_CTX")

    # Paths
    chroma_path: str = Field(default="./chroma_db", alias="CHROMA_PATH")
    data_path: str = Field(default="./data", alias="DATA_PATH")
    documents_path: str = Field(default="./documents", alias="DOCUMENTS_PATH")

    # Voice
    whisper_model: str = Field(default="base.en", alias="WHISPER_MODEL")
    tts_voice: str = Field(default="en-US-AriaNeural", alias="TTS_VOICE")
    tts_backend: str = Field(default="auto", alias="TTS_BACKEND")

    # RAG
    top_k_chunks: int = Field(default=3, alias="TOP_K_CHUNKS")
    chunk_size: int = Field(default=512, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=50, alias="CHUNK_OVERLAP")

    # Session
    session_timeout_minutes: int = Field(default=30, alias="SESSION_TIMEOUT_MINUTES")
    max_sessions: int = Field(default=50, alias="MAX_SESSIONS")

    # Generation
    llm_stream_max_tokens: int = Field(default=128, alias="LLM_STREAM_MAX_TOKENS")
    llm_tool_max_tokens: int = Field(default=48, alias="LLM_TOOL_MAX_TOKENS")
    llm_prompt_reserve_tokens: int = Field(default=256, alias="LLM_PROMPT_RESERVE_TOKENS")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def project_root(self) -> Path:
        """Return absolute path to repository root."""
        return Path(__file__).resolve().parent.parent

    @property
    def llm_model_file(self) -> Path:
        """Return absolute path of the GGUF model file."""
        return (self.project_root / self.llm_model_path).resolve()

    @property
    def chroma_dir(self) -> Path:
        """Return absolute path to persistent ChromaDB directory."""
        return (self.project_root / self.chroma_path).resolve()

    @property
    def data_dir(self) -> Path:
        """Return absolute path to SQLite data directory."""
        return (self.project_root / self.data_path).resolve()

    @property
    def documents_dir(self) -> Path:
        """Return absolute path to SEC documents directory."""
        return (self.project_root / self.documents_path).resolve()

    @property
    def latency_db_path(self) -> Path:
        """Return absolute path to latency SQLite database."""
        return self.data_dir / "latency.db"

    @property
    def crm_db_path(self) -> Path:
        """Return absolute path to CRM SQLite database."""
        return self.data_dir / "crm.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get singleton settings instance."""
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    return settings
