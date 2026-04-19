"""Base interface and return models for callable assistant tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Standardized tool execution result."""

    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: float


class BaseTool(ABC):
    """Abstract base class for all assistant tools."""

    name: str
    description: str
    parameters_schema: dict[str, Any]

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute tool logic with validated keyword arguments."""

    def to_llm_spec(self) -> dict[str, Any]:
        """Return compact tool spec for prompt/tool-selection contexts."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }
