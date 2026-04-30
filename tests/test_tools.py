from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.tool_orchestrator import ToolOrchestrator
from backend.tools.base_tool import BaseTool, ToolResult
from backend.tools.calculator_tool import CalculatorTool
from backend.tools.crm_tool import CRMTool
from backend.tools.news_tool import NewsTool
from backend.tools.stock_price_tool import StockPriceTool


@pytest.mark.asyncio
async def test_crm_create_user(tmp_path: Path) -> None:
    crm = CRMTool(db_path=str(tmp_path / "crm.db"))
    await crm.initialize()

    user = await crm.create_user("u1", "Alex")
    assert user["user_id"] == "u1"
    assert user["name"] == "Alex"


@pytest.mark.asyncio
async def test_crm_update_watchlist(tmp_path: Path) -> None:
    crm = CRMTool(db_path=str(tmp_path / "crm.db"))
    await crm.initialize()
    await crm.create_user("u2", "Sam")

    ok = await crm.add_to_watchlist("u2", "AAPL")
    assert ok is True

    user = await crm.get_user("u2")
    assert "AAPL" in user["watchlist"]


@pytest.mark.asyncio
async def test_crm_full_workflow_and_execute(tmp_path: Path) -> None:
    crm = CRMTool(db_path=str(tmp_path / "crm.db"))
    await crm.initialize()

    created = await crm.execute(action="create_user", user_id="u3", name="Taylor")
    assert created.success is True
    assert created.data["user"]["name"] == "Taylor"

    updated = await crm.execute(
        action="update_field",
        user_id="u3",
        field="risk_profile",
        value="moderate",
    )
    assert updated.success is True
    assert updated.data["updated"] is True

    watchlisted = await crm.execute(action="add_to_watchlist", user_id="u3", ticker="msft")
    assert watchlisted.success is True
    assert watchlisted.data["ticker"] == "MSFT"

    logged = await crm.execute(
        action="log_interaction",
        user_id="u3",
        session_id="s-1",
        summary="Discussed diversification",
    )
    assert logged.success is True
    assert logged.data["logged"] is True

    fetched = await crm.execute(action="get_user", user_id="u3")
    assert fetched.success is True
    assert fetched.data["user"]["risk_profile"] == "moderate"
    assert "MSFT" in fetched.data["user"]["watchlist"]

    history = await crm.execute(action="get_interaction_history", user_id="u3", limit=5)
    assert history.success is True
    assert history.data["history"]
    assert history.data["history"][0]["summary"] == "Discussed diversification"


@pytest.mark.asyncio
async def test_stock_price_invalid_ticker() -> None:
    tool = StockPriceTool()
    result = await tool.execute(ticker="INVALIDXYZ123")
    assert result.success is False


@pytest.mark.asyncio
async def test_stock_price_valid_ticker_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = StockPriceTool()

    def fake_fetch_sync(ticker: str):
        return {
            "ticker": ticker,
            "price": 189.43,
            "change_pct": 1.24,
            "volume": 54231000,
            "market_cap": "2.94T",
            "pe_ratio": 29.4,
            "dividend_yield": 0.52,
            "52w_high": 199.62,
            "52w_low": 124.17,
            "currency": "USD",
            "market_closed": False,
        }

    monkeypatch.setattr(tool, "_fetch_sync", fake_fetch_sync)
    result = await tool.execute(ticker="AAPL")

    assert result.success is True
    assert result.data["ticker"] == "AAPL"
    assert result.data["price"] == pytest.approx(189.43)


@pytest.mark.asyncio
async def test_calculator_roi() -> None:
    tool = CalculatorTool()
    result = await tool.execute(
        calculation_type="roi",
        params={"cost_basis": 150, "current_value": 248},
    )
    assert result.success is True
    assert result.data["result"] == pytest.approx(65.3333, rel=1e-3)


@pytest.mark.asyncio
async def test_calculator_cagr() -> None:
    tool = CalculatorTool()
    result = await tool.execute(
        calculation_type="cagr",
        params={"start_value": 100, "end_value": 133.1, "years": 3},
    )
    assert result.success is True
    assert result.data["result"] == pytest.approx(10.0, rel=1e-2)


@pytest.mark.asyncio
async def test_news_fetcher() -> None:
    tool = NewsTool()
    result = await tool.execute(query="AAPL", max_results=2)
    assert "count" in result.data


class SlowTool(BaseTool):
    name = "slow_tool"
    description = "slow"
    parameters_schema = {}

    async def execute(self, **kwargs):  # type: ignore[override]
        await asyncio.sleep(11)
        return ToolResult(success=True, data={}, duration_ms=11000)


@pytest.mark.asyncio
async def test_tool_timeout_handling() -> None:
    async def fake_detector(_: str) -> str:
        return '{"tool": "slow_tool", "params": {}}'

    orchestrator = ToolOrchestrator([SlowTool()], llm_intent_detector=fake_detector)
    result = await orchestrator.detect_and_execute("run slow tool", "session-1")
    assert "slow_tool" in result.results
    assert result.results["slow_tool"]["success"] is False
