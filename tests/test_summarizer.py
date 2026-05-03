from __future__ import annotations

from backend.summarizer import ConversationSummarizer


def test_summarizer_interval() -> None:
    summarizer = ConversationSummarizer(summary_interval_turns=4)

    assert summarizer.should_summarize(4) is True
    assert summarizer.should_summarize(8) is True
    assert summarizer.should_summarize(3) is False


def test_summarizer_generates_compact_text() -> None:
    summarizer = ConversationSummarizer(max_summary_chars=400)
    history = [
        {"role": "user", "content": "Summarize AAPL 10-K revenue and margins."},
        {"role": "assistant", "content": "AAPL reported higher revenue and expanding services margins."},
        {"role": "user", "content": "Compare with MSFT guidance."},
        {"role": "assistant", "content": "MSFT guidance remained strong with cloud growth."},
    ]

    summary = summarizer.summarize(history, previous_summary="Prior context about portfolio goals.")
    assert "Prior summary" in summary
    assert "Recent user requests" in summary
    assert "Referenced tickers" in summary
    assert "AAPL" in summary
    assert "MSFT" in summary


def test_summarizer_generates_short_session_title() -> None:
    title = ConversationSummarizer.generate_title("Can you summarize AAPL 2023 10-K risk factors?")

    assert title == "Summarize AAPL 2023 10-K Risk"
    assert len(title) <= 48
