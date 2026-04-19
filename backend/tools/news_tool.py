"""News aggregation tool using free RSS feeds and short-lived caching."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import feedparser
from cachetools import TTLCache

from backend.tools.base_tool import BaseTool, ToolResult

REUTERS_FEED = "https://feeds.reuters.com/reuters/businessNews"
CNBC_FEED = "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"
MARKETWATCH_FEED = "https://feeds.marketwatch.com/marketwatch/marketpulse/"
YAHOO_FEED_TEMPLATE = "https://finance.yahoo.com/rss/headline?s={ticker}"


class NewsTool(BaseTool):
    """Fetches financial news headlines and summaries from RSS feeds."""

    name = "news_tool"
    description = "Get latest relevant news for a company or ticker from RSS feeds."
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self) -> None:
        self.cache: TTLCache[str, list[dict[str, str]]] = TTLCache(maxsize=128, ttl=300)

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize title text for deduplication."""
        return re.sub(r"\s+", " ", text.lower()).strip()

    @staticmethod
    def _feed_to_articles(feed: Any, source: str) -> list[dict[str, str]]:
        """Convert parsed feed entries to normalized article dictionaries."""
        articles: list[dict[str, str]] = []
        for entry in getattr(feed, "entries", []):
            articles.append(
                {
                    "title": str(entry.get("title", "")).strip(),
                    "summary": str(entry.get("summary", "")).strip(),
                    "url": str(entry.get("link", "")).strip(),
                    "published": str(entry.get("published", "")).strip(),
                    "source": source,
                }
            )
        return articles

    async def _parse_feed(self, url: str, source: str) -> list[dict[str, str]]:
        """Parse one feed URL with thread offloading."""
        cache_key = f"feed::{url}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        parsed = await asyncio.to_thread(feedparser.parse, url)
        articles = self._feed_to_articles(parsed, source)
        self.cache[cache_key] = articles
        return articles

    @staticmethod
    def _matches_query(article: dict[str, str], query: str) -> bool:
        """Check whether article appears relevant to query terms."""
        q = query.lower().strip()
        haystack = f"{article.get('title', '')} {article.get('summary', '')}".lower()
        return q in haystack

    @staticmethod
    def _deduplicate(articles: list[dict[str, str]]) -> list[dict[str, str]]:
        """Deduplicate by normalized title similarity baseline."""
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for article in articles:
            key = re.sub(r"[^a-z0-9 ]", "", article.get("title", "").lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(article)
        return deduped

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute RSS news retrieval and relevance filtering."""
        start = time.perf_counter()
        query = str(kwargs.get("query", "")).strip()
        max_results = int(kwargs.get("max_results", 5))

        if not query:
            return ToolResult(
                success=False,
                data={},
                error="query is required",
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )

        try:
            ticker_guess = query.upper().replace("$", "").split()[0]

            yahoo_url = YAHOO_FEED_TEMPLATE.format(ticker=ticker_guess)
            feeds = await asyncio.gather(
                self._parse_feed(yahoo_url, "Yahoo Finance"),
                self._parse_feed(REUTERS_FEED, "Reuters"),
                self._parse_feed(CNBC_FEED, "CNBC"),
                self._parse_feed(MARKETWATCH_FEED, "MarketWatch"),
            )

            yahoo_articles, reuters_articles, cnbc_articles, marketwatch_articles = feeds

            selected: list[dict[str, str]] = []
            for article in yahoo_articles:
                if self._matches_query(article, query):
                    selected.append(article)

            if len(selected) < max_results:
                for source_articles in (reuters_articles, cnbc_articles, marketwatch_articles):
                    for article in source_articles:
                        if self._matches_query(article, query):
                            selected.append(article)

            deduped = self._deduplicate(selected)
            final = deduped[:max_results]

            return ToolResult(
                success=True,
                data={"query": query, "articles": final, "count": len(final)},
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                data={},
                error=str(exc),
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
