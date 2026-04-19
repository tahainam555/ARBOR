"""Stock market data tool backed by yfinance with short-lived caching."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import yfinance as yf
from cachetools import TTLCache

from backend.tools.base_tool import BaseTool, ToolResult


def _format_large_number(value: float | int | None) -> str | None:
    """Format market-cap style values with K/M/B/T suffixes."""
    if value is None:
        return None

    num = float(value)
    abs_num = abs(num)
    if abs_num >= 1_000_000_000_000:
        return f"{num / 1_000_000_000_000:.2f}T"
    if abs_num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.2f}B"
    if abs_num >= 1_000_000:
        return f"{num / 1_000_000:.2f}M"
    if abs_num >= 1_000:
        return f"{num / 1_000:.2f}K"
    return f"{num:.2f}"


class StockPriceTool(BaseTool):
    """Fetches and caches real-time-ish stock market snapshots."""

    name = "stock_price"
    description = "Fetch current stock price and key market metrics for tickers."
    parameters_schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "tickers": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": False,
    }

    def __init__(self) -> None:
        self.cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=256, ttl=60)

    def _fetch_sync(self, ticker: str) -> dict[str, Any]:
        """Synchronous yfinance fetch for one ticker symbol."""
        symbol = ticker.upper().strip()
        if not symbol:
            raise ValueError("Ticker cannot be empty")

        stock = yf.Ticker(symbol)
        info = stock.info or {}

        if not info or (info.get("regularMarketPrice") is None and info.get("currentPrice") is None):
            raise ValueError(f"Ticker '{symbol}' not found")

        regular_market_price = info.get("regularMarketPrice") or info.get("currentPrice")
        previous_close = info.get("regularMarketPreviousClose") or info.get("previousClose")

        change_pct = None
        if regular_market_price is not None and previous_close not in (None, 0):
            change_pct = ((float(regular_market_price) - float(previous_close)) / float(previous_close)) * 100.0

        market_state = str(info.get("marketState", "")).upper()
        market_closed = market_state not in {"REGULAR", "PRE", "POST", "PREPRE", "POSTPOST"}

        return {
            "ticker": symbol,
            "price": round(float(regular_market_price), 4) if regular_market_price is not None else None,
            "change_pct": round(float(change_pct), 4) if change_pct is not None else None,
            "volume": info.get("regularMarketVolume") or info.get("volume"),
            "market_cap": _format_large_number(info.get("marketCap")),
            "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
            "dividend_yield": round(float(info.get("dividendYield") * 100.0), 4)
            if info.get("dividendYield") is not None
            else None,
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "currency": info.get("currency", "USD"),
            "market_closed": market_closed,
        }

    async def _fetch_one(self, ticker: str) -> dict[str, Any]:
        """Fetch one ticker with cache and thread offloading."""
        symbol = ticker.upper().strip()
        if symbol in self.cache:
            return self.cache[symbol]

        data = await asyncio.to_thread(self._fetch_sync, symbol)
        self.cache[symbol] = data
        return data

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute stock lookup for one or multiple tickers."""
        start = time.perf_counter()
        try:
            single = kwargs.get("ticker")
            multi = kwargs.get("tickers")

            if single:
                data = await self._fetch_one(str(single))
                return ToolResult(
                    success=True,
                    data=data,
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )

            if multi:
                symbols = [str(item).upper() for item in multi]
                results = await asyncio.gather(*(self._fetch_one(sym) for sym in symbols), return_exceptions=True)

                payload: dict[str, Any] = {}
                errors: dict[str, str] = {}
                for sym, result in zip(symbols, results):
                    if isinstance(result, Exception):
                        errors[sym] = str(result)
                    else:
                        payload[sym] = result

                return ToolResult(
                    success=len(payload) > 0,
                    data={"results": payload, "errors": errors},
                    error=None if len(errors) == 0 else "Some tickers failed",
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )

            raise ValueError("Provide ticker or tickers")
        except ValueError as exc:
            return ToolResult(
                success=False,
                data={},
                error=str(exc),
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
        except Exception:
            return ToolResult(
                success=False,
                data={},
                error="Market data unavailable, try again",
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
