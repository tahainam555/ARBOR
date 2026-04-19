from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest

from backend.rag.indexer import SECIndexer
from backend.rag.retriever import RAGRetriever


def _create_pdf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text, fontsize=11)
    doc.save(path)
    doc.close()


@pytest.mark.asyncio
async def test_indexing_pipeline(tmp_path: Path) -> None:
    docs = tmp_path / "documents"
    _create_pdf(docs / "AAPL" / "AAPL_10K_2023.pdf", "Apple revenue was strong in 2023.")
    _create_pdf(docs / "MSFT" / "MSFT_10K_2023.pdf", "Microsoft cloud revenue increased.")
    _create_pdf(docs / "TSLA" / "TSLA_10K_2023.pdf", "Tesla R&D spending expanded.")

    indexer = SECIndexer(chroma_path=str(tmp_path / "chroma"))
    summary = indexer.index_documents(documents_path=docs)

    assert summary.indexed_documents == 3
    assert summary.indexed_chunks >= 3


@pytest.mark.asyncio
async def test_retrieval_relevance(tmp_path: Path) -> None:
    docs = tmp_path / "documents"
    _create_pdf(docs / "AAPL" / "AAPL_10K_2023.pdf", "Apple revenue reached a record value.")

    chroma_path = str(tmp_path / "chroma")
    SECIndexer(chroma_path=chroma_path).index_documents(documents_path=docs)
    retriever = RAGRetriever(chroma_path=chroma_path)

    chunks = await retriever.retrieve("Apple revenue", top_k=3)
    assert len(chunks) > 0
    assert any(c.ticker == "AAPL" for c in chunks)


@pytest.mark.asyncio
async def test_filter_by_ticker(tmp_path: Path) -> None:
    docs = tmp_path / "documents"
    _create_pdf(docs / "AAPL" / "AAPL_10K_2023.pdf", "Apple revenue details.")
    _create_pdf(docs / "MSFT" / "MSFT_10K_2023.pdf", "Microsoft revenue details.")

    chroma_path = str(tmp_path / "chroma")
    SECIndexer(chroma_path=chroma_path).index_documents(documents_path=docs)
    retriever = RAGRetriever(chroma_path=chroma_path)

    chunks = await retriever.retrieve("revenue", top_k=5, filter_ticker="AAPL")
    assert len(chunks) > 0
    assert all(c.ticker == "AAPL" for c in chunks)


@pytest.mark.asyncio
async def test_retrieval_latency(tmp_path: Path) -> None:
    docs = tmp_path / "documents"
    _create_pdf(docs / "AAPL" / "AAPL_10K_2023.pdf", "Apple revenue details in filing.")

    chroma_path = str(tmp_path / "chroma")
    SECIndexer(chroma_path=chroma_path).index_documents(documents_path=docs)
    retriever = RAGRetriever(chroma_path=chroma_path)

    await retriever.retrieve("Apple revenue", top_k=3)
    start = time.perf_counter()
    await retriever.retrieve("Apple revenue", top_k=3)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert elapsed_ms < 2000
