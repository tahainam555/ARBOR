"""Heuristic domain classifier for SEC investment research requests."""

from __future__ import annotations

from dataclasses import dataclass
import re


COMPANY_KEYWORDS = {
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

POSITIVE_KEYWORDS = {
    "sec",
    "10-k",
    "10-q",
    "8-k",
    "def 14a",
    "def14a",
    "filing",
    "filings",
    "annual report",
    "quarterly report",
    "earnings",
    "revenue",
    "net income",
    "cash flow",
    "balance sheet",
    "income statement",
    "market cap",
    "stock price",
    "share price",
    "ticker",
    "valuation",
    "portfolio",
    "dividend",
    "pe ratio",
    "cagr",
    "roi",
    "watchlist",
    "guidance",
    "management discussion",
    "risk factors",
    "news",
    "investor relations",
}

NEGATIVE_KEYWORDS = {
    "weather",
    "joke",
    "recipe",
    "movie",
    "song",
    "lyrics",
    "poem",
    "sports score",
    "sports",
    "politics",
    "travel",
    "history homework",
    "math homework",
    "code review",
    "translate",
    "calendar",
}


@dataclass(frozen=True)
class DomainDecision:
    """Outcome of a domain classification pass."""

    allowed: bool
    reason: str
    confidence: float


class DomainClassifier:
    """Lightweight SEC-domain gate for user messages."""

    @staticmethod
    def _has_ticker(message: str) -> bool:
        upper_tokens = re.findall(r"\b[A-Z]{2,5}\b", message)
        return any(token not in {"ROI", "CAGR", "SEC", "DEF", "ETF", "EPS", "PEG"} for token in upper_tokens)

    @staticmethod
    def _has_company(message: str) -> bool:
        lower = message.lower()
        return any(company in lower for company in COMPANY_KEYWORDS)

    def classify(self, message: str) -> DomainDecision:
        """Return whether a message is in the SEC/investment research domain."""
        normalized = message.strip()
        if not normalized:
            return DomainDecision(False, "empty message", 0.0)

        lower = normalized.lower()
        if any(phrase in lower for phrase in NEGATIVE_KEYWORDS):
            return DomainDecision(False, "outside SEC/investment scope", 0.98)

        positive_hits = sum(1 for keyword in POSITIVE_KEYWORDS if keyword in lower)
        has_ticker = self._has_ticker(normalized)
        has_company = self._has_company(normalized)

        if has_ticker or has_company:
            return DomainDecision(True, "mentions a public company or ticker", 0.95)

        if positive_hits >= 2:
            return DomainDecision(True, "contains multiple SEC/investment signals", min(0.9, 0.55 + positive_hits * 0.1))

        if positive_hits == 1:
            return DomainDecision(True, "contains an SEC/investment signal", 0.7)

        return DomainDecision(
            False,
            "message does not appear to be about SEC filings, public companies, market data, or investing",
            0.25,
        )
