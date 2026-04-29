"""Lightweight conversation summarization for long-running sessions."""

from __future__ import annotations

import re


class ConversationSummarizer:
    """Build compact running summaries from recent chat history."""

    def __init__(
        self,
        summary_interval_turns: int = 4,
        max_history_messages: int = 12,
        max_summary_chars: int = 900,
    ) -> None:
        self.summary_interval_turns = summary_interval_turns
        self.max_history_messages = max_history_messages
        self.max_summary_chars = max_summary_chars

    def should_summarize(self, turn_count: int) -> bool:
        """Return whether this turn should trigger summary refresh."""
        if turn_count <= 0:
            return False
        return turn_count % self.summary_interval_turns == 0

    @staticmethod
    def _normalize(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        return cleaned

    @staticmethod
    def _extract_tickers(history: list[dict[str, str]]) -> list[str]:
        symbols: set[str] = set()
        for message in history:
            symbols.update(re.findall(r"\b[A-Z]{2,5}\b", message.get("content", "")))
        blocked = {"ROI", "CAGR", "SEC", "ETF", "EPS", "PEG", "DEF"}
        filtered = sorted(symbol for symbol in symbols if symbol not in blocked)
        return filtered[:8]

    def summarize(self, history: list[dict[str, str]], previous_summary: str | None = None) -> str:
        """Generate a concise running summary from chat history."""
        if not history:
            return previous_summary or ""

        recent = history[-self.max_history_messages :]
        user_lines = [self._normalize(item.get("content", "")) for item in recent if item.get("role") == "user"]
        assistant_lines = [self._normalize(item.get("content", "")) for item in recent if item.get("role") == "assistant"]

        fragments: list[str] = []
        if previous_summary:
            fragments.append(f"Prior summary: {self._normalize(previous_summary)}")

        if user_lines:
            fragments.append("Recent user requests: " + " | ".join(user_lines[-3:]))

        if assistant_lines:
            fragments.append("Recent assistant findings: " + " | ".join(assistant_lines[-3:]))

        tickers = self._extract_tickers(recent)
        if tickers:
            fragments.append("Referenced tickers: " + ", ".join(tickers))

        summary = "\n".join(fragment for fragment in fragments if fragment)
        if len(summary) <= self.max_summary_chars:
            return summary
        return summary[-self.max_summary_chars :]

    @staticmethod
    def generate_title(text: str, fallback: str = "Conversation") -> str:
        """Generate a short stable title from the first meaningful user request."""
        cleaned = re.sub(r"[^\w\s$.-]", " ", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return fallback

        stopwords = {
            "a",
            "an",
            "and",
            "about",
            "can",
            "could",
            "for",
            "from",
            "give",
            "help",
            "how",
            "i",
            "in",
            "is",
            "me",
            "of",
            "on",
            "please",
            "show",
            "tell",
            "the",
            "to",
            "what",
            "with",
            "you",
        }
        words = [word for word in cleaned.split() if word.lower() not in stopwords]
        if not words:
            words = cleaned.split()

        def format_word(word: str) -> str:
            if re.fullmatch(r"\$?[A-Z]{2,5}", word) or re.search(r"\d", word):
                return word.upper()
            return word.capitalize()

        title = " ".join(format_word(word) for word in words[:5]).strip()
        if not title:
            return fallback

        return title[:48]
