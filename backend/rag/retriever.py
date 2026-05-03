"""RAG retrieval over indexed SEC filings in ChromaDB."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import chromadb
from sentence_transformers import SentenceTransformer

from backend.config import get_settings


@dataclass(frozen=True)
class RetrievedChunk:
    """Retrieved context chunk with source metadata and distance score."""

    id: str
    text: str
    source: str
    ticker: str
    company: str
    filing_type: str
    year: str
    chunk_index: int
    score: float


class RAGRetriever:
    """Retrieves top-k SEC chunks from persistent ChromaDB."""

    def __init__(self, chroma_path: str | None = None) -> None:
        self.settings = get_settings()
        target_chroma = str(self.settings.chroma_dir) if chroma_path is None else chroma_path
        self.client = chromadb.PersistentClient(path=target_chroma)
        self.collection = self.client.get_or_create_collection(name="sec_filings")
        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

    async def _embed_query(self, query: str) -> list[float]:
        """Embed query text with local MiniLM model in a worker thread."""
        vector = await asyncio.to_thread(self.embedding_model.encode, query)
        return vector.tolist() if hasattr(vector, "tolist") else list(vector)

    async def warmup(self) -> None:
        """Prime embedding and vector query paths to lower first-turn latency."""
        embedding = await self._embed_query("sec filing warmup query")
        await self.retrieve_with_embedding(query_embedding=embedding, top_k=1)

    @staticmethod
    def _build_where(filter_ticker: str | None, filter_year: str | None) -> dict | None:
        """Build optional ChromaDB metadata filter object."""
        conditions: list[dict[str, str]] = []
        if filter_ticker:
            conditions.append({"ticker": filter_ticker.upper()})
        if filter_year:
            conditions.append({"year": str(filter_year)})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    async def retrieve_with_embedding(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filter_ticker: str | None = None,
        filter_year: str | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve top-k chunks from a precomputed query embedding."""
        where = self._build_where(filter_ticker=filter_ticker, filter_year=filter_year)

        result = await asyncio.to_thread(
            self.collection.query,
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        docs = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        chunks: list[RetrievedChunk] = []
        for idx, text in enumerate(docs):
            meta = metadatas[idx] if idx < len(metadatas) else {}
            distance = float(distances[idx]) if idx < len(distances) else 0.0
            ticker = str(meta.get("ticker", "unknown"))
            filing_type = str(meta.get("filing_type", "unknown"))
            year = str(meta.get("year", "unknown"))
            chunk_index = int(meta.get("chunk_index", -1))
            chunks.append(
                RetrievedChunk(
                    id=f"{ticker}_{filing_type.replace('-', '').replace(' ', '')}_{year}_chunk_{chunk_index}",
                    text=text,
                    source=str(meta.get("source_file", "unknown")),
                    ticker=ticker,
                    company=str(meta.get("company", "unknown")),
                    filing_type=filing_type,
                    year=year,
                    chunk_index=chunk_index,
                    score=distance,
                )
            )

        return chunks

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filter_ticker: str | None = None,
        filter_year: str | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve top-k semantically relevant filing chunks."""
        embedding = await self._embed_query(query)
        return await self.retrieve_with_embedding(
            query_embedding=embedding,
            top_k=top_k,
            filter_ticker=filter_ticker,
            filter_year=filter_year,
        )

    async def format_context(self, chunks: list[RetrievedChunk], max_tokens: int = 800) -> str:
        """Format retrieved chunks for LLM prompt with context truncation."""
        context_blocks: list[str] = []
        token_budget = max_tokens

        for chunk in chunks:
            block = (
                f"[Source: {chunk.ticker} {chunk.filing_type} {chunk.year}]\n"
                f"{chunk.text.strip()}\n"
            )

            estimated_tokens = max(1, int(len(block.split()) * 1.3))
            if estimated_tokens > token_budget:
                break

            context_blocks.append(block)
            token_budget -= estimated_tokens

        return "\n".join(context_blocks)
