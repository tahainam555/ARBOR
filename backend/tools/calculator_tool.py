"""Financial calculator tool for common investment computations."""

from __future__ import annotations

import math
import time
from typing import Any

from backend.tools.base_tool import BaseTool, ToolResult


class CalculatorTool(BaseTool):
    """Performs deterministic financial calculations."""

    name = "calculator"
    description = "Compute ROI, CAGR, compound interest, PE ratio, and other finance formulas."
    parameters_schema = {
        "type": "object",
        "properties": {
            "calculation_type": {"type": "string"},
            "params": {"type": "object"},
        },
        "required": ["calculation_type", "params"],
        "additionalProperties": False,
    }

    @staticmethod
    def _roi(params: dict[str, Any]) -> dict[str, Any]:
        cost_basis = float(params["cost_basis"])
        current_value = float(params["current_value"])
        result = ((current_value - cost_basis) / cost_basis) * 100.0
        return {
            "result": result,
            "formula_used": "(current_value - cost_basis) / cost_basis * 100",
            "explanation": "Return on Investment in percent.",
        }

    @staticmethod
    def _cagr(params: dict[str, Any]) -> dict[str, Any]:
        start_value = float(params["start_value"])
        end_value = float(params["end_value"])
        years = float(params["years"])
        result = (math.pow((end_value / start_value), (1.0 / years)) - 1.0) * 100.0
        return {
            "result": result,
            "formula_used": "((end_value/start_value)^(1/years) - 1) * 100",
            "explanation": "Compound Annual Growth Rate in percent.",
        }

    @staticmethod
    def _compound_interest(params: dict[str, Any]) -> dict[str, Any]:
        principal = float(params["principal"])
        rate_pct = float(params["rate_pct"])
        years = float(params["years"])
        compounds_per_year = int(params.get("compounds_per_year", 1))

        r = rate_pct / 100.0
        result = principal * math.pow((1.0 + (r / compounds_per_year)), compounds_per_year * years)
        return {
            "result": result,
            "formula_used": "P(1 + r/n)^(nt)",
            "explanation": "Future value using compound interest.",
        }

    @staticmethod
    def _pe_ratio(params: dict[str, Any]) -> dict[str, Any]:
        stock_price = float(params["stock_price"])
        eps = float(params["eps"])
        result = stock_price / eps
        return {
            "result": result,
            "formula_used": "stock_price / eps",
            "explanation": "Price-to-earnings ratio.",
        }

    @staticmethod
    def _dividend_yield(params: dict[str, Any]) -> dict[str, Any]:
        annual_dividend = float(params["annual_dividend"])
        stock_price = float(params["stock_price"])
        result = (annual_dividend / stock_price) * 100.0
        return {
            "result": result,
            "formula_used": "annual_dividend / stock_price * 100",
            "explanation": "Dividend yield percentage.",
        }

    @staticmethod
    def _portfolio_value(params: dict[str, Any]) -> dict[str, Any]:
        holdings = params["holdings"]
        total = 0.0
        for holding in holdings:
            shares = float(holding["shares"])
            current_price = float(holding["current_price"])
            total += shares * current_price

        return {
            "result": total,
            "formula_used": "sum(shares * current_price)",
            "explanation": "Total current portfolio market value.",
        }

    @staticmethod
    def _break_even(params: dict[str, Any]) -> dict[str, Any]:
        cost_basis = float(params["cost_basis"])
        target_return_pct = float(params["target_return_pct"])
        result = cost_basis * (1.0 + target_return_pct / 100.0)
        return {
            "result": result,
            "formula_used": "cost_basis * (1 + target_return_pct/100)",
            "explanation": "Target value needed to reach desired return.",
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a supported financial calculation."""
        start = time.perf_counter()
        try:
            calc_type = str(kwargs.get("calculation_type", "")).strip().lower()
            params = kwargs.get("params")
            if not calc_type or not isinstance(params, dict):
                raise ValueError("calculation_type and params are required")

            calculators = {
                "roi": self._roi,
                "cagr": self._cagr,
                "compound_interest": self._compound_interest,
                "pe_ratio": self._pe_ratio,
                "dividend_yield": self._dividend_yield,
                "portfolio_value": self._portfolio_value,
                "break_even": self._break_even,
            }

            if calc_type not in calculators:
                raise ValueError(f"Unsupported calculation_type: {calc_type}")

            data = calculators[calc_type](params)
            return ToolResult(
                success=True,
                data=data,
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
        except (KeyError, ValueError, ZeroDivisionError) as exc:
            return ToolResult(
                success=False,
                data={},
                error=str(exc),
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
