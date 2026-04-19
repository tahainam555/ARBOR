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
async def test_stock_price_invalid_ticker() -> None:
    tool = StockPriceTool()
    result = await tool.execute(ticker="INVALIDXYZ123")
    assert result.success is False


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
    orchestrator = ToolOrchestrator([SlowTool()])

    with pytest.raises(asyncio.TimeoutError):
        await orchestrator._execute_one("slow_tool", {})
