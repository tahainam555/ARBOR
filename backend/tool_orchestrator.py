"""Tool detection and execution orchestrator for user requests."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from backend.tools.base_tool import BaseTool, ToolResult


@dataclass
class ToolExecutionResult:
    """Result bundle from detect-and-execute orchestration."""

    detections: list[dict[str, Any]] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    formatted_context: str = ""
    duration_ms: float = 0.0


class ToolOrchestrator:
    """Detects tool intent and runs tools with robust timeouts."""

    def __init__(
        self,
        tools: list[BaseTool],
        llm_intent_detector: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        self.tools: dict[str, BaseTool] = {tool.name: tool for tool in tools}
        self.llm_intent_detector = llm_intent_detector

    @staticmethod
    def _extract_ticker(message: str) -> str | None:
        """Try extracting a likely ticker symbol from message text."""
        explicit = re.findall(r"\$([A-Za-z]{1,5})\b", message)
        if explicit:
            return explicit[0].upper()

        upper_tokens = re.findall(r"\b[A-Z]{2,5}\b", message)
        for token in upper_tokens:
            if token not in {"ROI", "CAGR", "DEF", "SEC", "ETF"}:
                return token

        company_to_ticker = {
            "apple": "AAPL",
            "microsoft": "MSFT",
            "tesla": "TSLA",
            "amazon": "AMZN",
            "google": "GOOGL",
            "alphabet": "GOOGL",
            "jpmorgan": "JPM",
            "johnson": "JNJ",
            "exxon": "XOM",
            "walmart": "WMT",
            "nvidia": "NVDA",
        }
        lower = message.lower()
        for company, ticker in company_to_ticker.items():
            if company in lower:
                return ticker

        return None

    def _rule_based_detection(self, message: str) -> list[dict[str, Any]]:
        """Fast keyword/regex based intent detection before any LLM fallback."""
        lower = message.lower()
        detected: list[dict[str, Any]] = []

        price_patterns = ["price of", "trading at", "current price", "stock price"]
        if any(pattern in lower for pattern in price_patterns):
            ticker = self._extract_ticker(message)
            if ticker:
                detected.append({"tool": "stock_price", "params": {"ticker": ticker}})

        calc_patterns = [
            "calculate roi",
            "roi",
            "cagr",
            "compound interest",
            "break even",
            "pe ratio",
            "dividend yield",
            "portfolio value",
            "future value",
            "if i bought",
            "if i invest",
        ]
        has_calculator_intent = any(pattern in lower for pattern in calc_patterns)
        if "calculate" in lower and re.search(r"\d", message):
            has_calculator_intent = True

        if has_calculator_intent:
            detected.append({"tool": "calculator", "params": self._infer_calculator_params(message)})

        news_patterns = ["news about", "latest on", "recent news", "what happened with"]
        if any(pattern in lower for pattern in news_patterns):
            query = self._extract_ticker(message) or message
            detected.append({"tool": "news_tool", "params": {"query": query, "max_results": 5}})

        crm_actions: list[dict[str, Any]] = []

        name_match = re.search(r"\b(?:my name is|call me)\s+([^.,!?;]+)", message, flags=re.IGNORECASE)
        if name_match:
            candidate = re.split(r"\b(?:and|but|because|so|with|for|to|if)\b", name_match.group(1), maxsplit=1, flags=re.IGNORECASE)[0].strip()
            crm_actions.append(
                {
                    "tool": "crm_tool",
                    "params": {
                        "action": "update_field",
                        "user_id": "default_user",
                        "field": "name",
                        "value": candidate,
                    },
                }
            )

        risk_match = re.search(
            r"\b(?:i am|i'm|i prefer|my risk tolerance is)\s+(?:a\s+|an\s+)?(conservative|moderate|aggressive)\b",
            message,
            flags=re.IGNORECASE,
        )
        if risk_match:
            crm_actions.append(
                {
                    "tool": "crm_tool",
                    "params": {
                        "action": "update_field",
                        "user_id": "default_user",
                        "field": "risk_profile",
                        "value": risk_match.group(1).lower(),
                    },
                }
            )

        if "watchlist" in lower or "watching" in lower or "keep an eye on" in lower:
            ticker = self._extract_ticker(message)
            if ticker:
                crm_actions.append(
                    {
                        "tool": "crm_tool",
                        "params": {
                            "action": "add_to_watchlist",
                            "user_id": "default_user",
                            "ticker": ticker,
                        },
                    }
                )

        if any(pattern in lower for pattern in ("remember me", "my profile", "i'm back", "update my")):
            crm_actions.append(
                {
                    "tool": "crm_tool",
                    "params": {
                        "action": "get_user",
                        "user_id": "default_user",
                    },
                }
            )

        detected.extend(crm_actions)

        return detected

    @staticmethod
    def _should_try_llm_detection(message: str) -> bool:
        """Gate LLM intent detection to likely tool requests only for lower latency."""
        lower = message.lower()
        hints = (
            "price",
            "trading",
            "ticker",
            "tool",
            "news",
            "headline",
            "latest",
            "update",
            "calculate",
            "roi",
            "cagr",
            "compound",
            "break even",
            "dividend",
            "profile",
            "watchlist",
            "remember me",
            "my account",
            "portfolio",
        )
        return any(hint in lower for hint in hints)

    @staticmethod
    def _infer_calculator_params(message: str) -> dict[str, Any]:
        """Infer minimal calculator payload from plain-language user text."""
        lower = message.lower()

        if "roi" in lower:
            numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", message)]
            if len(numbers) >= 2:
                return {
                    "calculation_type": "roi",
                    "params": {"cost_basis": numbers[0], "current_value": numbers[1]},
                }

        if "cagr" in lower:
            numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", message)]
            if len(numbers) >= 3:
                return {
                    "calculation_type": "cagr",
                    "params": {
                        "start_value": numbers[0],
                        "end_value": numbers[1],
                        "years": numbers[2],
                    },
                }

        return {
            "calculation_type": "roi",
            "params": {"cost_basis": 1.0, "current_value": 1.0},
        }

    async def _execute_one(self, tool_name: str, params: dict[str, Any]) -> ToolResult:
        """Execute one tool safely with timeout protection."""
        if tool_name not in self.tools:
            return ToolResult(success=False, data={}, error=f"Unknown tool: {tool_name}", duration_ms=0.0)

        tool = self.tools[tool_name]
        return await asyncio.wait_for(tool.execute(**params), timeout=10.0)

    @staticmethod
    def _format_results(results: dict[str, ToolResult]) -> str:
        """Format tool outputs for prompt context injection."""
        lines: list[str] = []
        for name, result in results.items():
            if result.success:
                lines.append(f"[{name}] {json.dumps(result.data, ensure_ascii=True)}")
            else:
                lines.append(f"[{name}] ERROR: {result.error}")
        return "\n".join(lines)

    async def _llm_based_detection(self, message: str) -> list[dict[str, Any]]:
        """Fallback intent detection for ambiguous requests using LLM JSON output."""
        if self.llm_intent_detector is None:
            return []

        if not self._should_try_llm_detection(message):
            return []

        prompt = (
            "Given this user message, which tool should be called? Output JSON only.\n"
            "Tools: [crm_tool, stock_price, calculator, news_tool, none]\n"
            f"User: {message}\n"
            "Response format: {\"tool\": \"stock_price\", \"params\": {\"ticker\": \"AAPL\"}}"
        )

        try:
            raw = await self.llm_intent_detector(prompt)
            json_match = re.search(r"\{[\s\S]*\}", raw)
            if not json_match:
                return []

            payload = json.loads(json_match.group(0))
            tool_name = str(payload.get("tool", "none")).strip()
            params = payload.get("params", {})
            if tool_name == "none" or tool_name not in self.tools:
                return []

            if not isinstance(params, dict):
                params = {}

            return [{"tool": tool_name, "params": params}]
        except Exception:
            return []

    async def detect_and_execute(self, message: str, session_id: str) -> ToolExecutionResult:
        """Detect candidate tools and execute them asynchronously."""
        del session_id  # Reserved for future session-aware routing.

        start = time.perf_counter()
        detections = self._rule_based_detection(message)
        if not detections:
            detections = await self._llm_based_detection(message)

        if not detections:
            return ToolExecutionResult(duration_ms=(time.perf_counter() - start) * 1000.0)

        tasks = [self._execute_one(item["tool"], item.get("params", {})) for item in detections]
        settled = await asyncio.gather(*tasks, return_exceptions=True)

        results: dict[str, ToolResult] = {}
        tools_called: list[str] = []

        for detection, outcome in zip(detections, settled):
            tool_name = detection["tool"]
            tools_called.append(tool_name)

            if isinstance(outcome, asyncio.TimeoutError):
                results[tool_name] = ToolResult(
                    success=False,
                    data={},
                    error="Tool execution timed out",
                    duration_ms=10000.0,
                )
            elif isinstance(outcome, Exception):
                results[tool_name] = ToolResult(
                    success=False,
                    data={},
                    error=f"Tool execution failed: {outcome}",
                    duration_ms=0.0,
                )
            else:
                results[tool_name] = outcome

        formatted = self._format_results(results)
        serializable_results = {tool: result.model_dump() for tool, result in results.items()}

        return ToolExecutionResult(
            detections=detections,
            tools_called=tools_called,
            results=serializable_results,
            formatted_context=formatted,
            duration_ms=(time.perf_counter() - start) * 1000.0,
        )
