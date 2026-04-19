"""Offline indexing pipeline for SEC filing documents."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from backend.config import get_settings
from backend.rag.chunker import SECChunker


@dataclass(frozen=True)
class IndexingSummary:
    """Indexing run metrics."""

    indexed_documents: int
    skipped_documents: int
    failed_documents: int
    indexed_chunks: int


class SECIndexer:
    """Indexes SEC filing chunks into persistent ChromaDB storage."""

    def __init__(self, chroma_path: str | None = None) -> None:
        self.settings = get_settings()
        target_chroma = str(self.settings.chroma_dir) if chroma_path is None else chroma_path
        self.client = chromadb.PersistentClient(path=target_chroma)
        self.embedding_function = SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self.collection: Collection = self.client.get_or_create_collection(
            name="sec_filings",
            embedding_function=self.embedding_function,
            metadata={"description": "SEC filings chunks for investment assistant"},
        )
        self.chunker = SECChunker(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )

    def _is_document_indexed(self, source_file: str) -> bool:
        """Check whether at least one chunk for a source file already exists."""
        existing = self.collection.get(
            where={"source_file": source_file},
            include=[],
            limit=1,
        )
        return bool(existing.get("ids"))

    def _make_chunk_id(self, ticker: str, filing_type: str, year: str, chunk_index: int) -> str:
        """Build deterministic chunk IDs for stable re-indexing."""
        normalized_filing = filing_type.replace("-", "").replace(" ", "")
        return f"{ticker}_{normalized_filing}_{year}_chunk_{chunk_index}"

    def _index_single_document(self, pdf_path: Path) -> tuple[int, bool]:
        """Index one PDF into ChromaDB.

        Returns:
            tuple[int, bool]: (chunk_count, skipped)
        """
        source_file = pdf_path.name
        if self._is_document_indexed(source_file):
            return 0, True

        chunks = self.chunker.chunk_pdf(pdf_path)
        if not chunks:
            return 0, False

        ids: list[str] = []
        texts: list[str] = []
        metadatas: list[dict[str, str | int]] = []

        for record in chunks:
            metadata = record.metadata
            chunk_id = self._make_chunk_id(
                ticker=str(metadata["ticker"]),
                filing_type=str(metadata["filing_type"]),
                year=str(metadata["year"]),
                chunk_index=int(metadata["chunk_index"]),
            )
            ids.append(chunk_id)
            texts.append(record.chunk_text)
            metadatas.append(metadata)

        self.collection.add(ids=ids, documents=texts, metadatas=metadatas)
        return len(chunks), False

    def index_documents(self, documents_path: Path | None = None) -> IndexingSummary:
        """Index all PDFs from documents directory recursively."""
        docs_root = documents_path or self.settings.documents_dir
        pdf_files = sorted(docs_root.rglob("*.pdf"))

        indexed_documents = 0
        skipped_documents = 0
        failed_documents = 0
        indexed_chunks = 0

        for pdf in pdf_files:
            try:
                chunk_count, skipped = self._index_single_document(pdf)
                if skipped:
                    skipped_documents += 1
                    logging.info("Skipped already-indexed %s", pdf.name)
                    continue

                indexed_documents += 1
                indexed_chunks += chunk_count
                logging.info("Indexed %s -> %s chunks", pdf.name, chunk_count)
            except Exception as exc:  # noqa: BLE001
                failed_documents += 1
                logging.exception("Failed indexing %s: %s", pdf, exc)

        logging.info(
            "Total: documents=%s indexed=%s skipped=%s failed=%s chunks=%s",
            len(pdf_files),
            indexed_documents,
            skipped_documents,
            failed_documents,
            indexed_chunks,
        )

        return IndexingSummary(
            indexed_documents=indexed_documents,
            skipped_documents=skipped_documents,
            failed_documents=failed_documents,
            indexed_chunks=indexed_chunks,
        )

    def get_indexed_documents(self) -> dict[str, int]:
        """Return indexed source file counts based on chunk metadata."""
        data = self.collection.get(include=["metadatas"])
        metadatas = data.get("metadatas", [])

        counts: dict[str, int] = {}
        for item in metadatas:
            source_file = str(item.get("source_file", "unknown"))
            counts[source_file] = counts.get(source_file, 0) + 1

        return counts
