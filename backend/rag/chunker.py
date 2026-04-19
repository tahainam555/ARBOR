"""PDF text extraction and chunking utilities for SEC filings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import fitz
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.config import get_settings

COMPANY_NAMES: dict[str, str] = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "TSLA": "Tesla, Inc.",
    "AMZN": "Amazon.com, Inc.",
    "GOOGL": "Alphabet Inc.",
    "JPM": "JPMorgan Chase & Co.",
    "JNJ": "Johnson & Johnson",
    "XOM": "Exxon Mobil Corporation",
    "WMT": "Walmart Inc.",
    "NVDA": "NVIDIA Corporation",
}


@dataclass(frozen=True)
class FilingMetadata:
    """Normalized filing metadata inferred from file and folder naming."""

    source_file: str
    company: str
    ticker: str
    filing_type: str
    year: str


@dataclass(frozen=True)
class ChunkRecord:
    """One chunk with normalized metadata."""

    chunk_text: str
    metadata: dict[str, str | int]


class SECChunker:
    """Convert SEC filing PDFs into RAG-ready text chunks."""

    def __init__(self, chunk_size: int | None = None, chunk_overlap: int | None = None) -> None:
        settings = get_settings()
        self.chunk_size = chunk_size if chunk_size is not None else settings.chunk_size
        self.chunk_overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
            keep_separator=False,
        )

    def extract_pdf_pages(self, pdf_path: Path) -> list[str]:
        """Extract raw text page by page from a PDF file."""
        doc = fitz.open(pdf_path)
        try:
            pages: list[str] = []
            for page in doc:
                text = page.get_text("text")
                clean = re.sub(r"\s+", " ", text).strip()
                pages.append(clean)
            return pages
        finally:
            doc.close()

    def parse_metadata(self, pdf_path: Path) -> FilingMetadata:
        """Parse ticker, filing type, and year from standardized filename."""
        filename = pdf_path.name
        stem = pdf_path.stem
        parts = stem.split("_")

        if len(parts) < 3:
            raise ValueError(f"Unexpected filing filename format: {filename}")

        ticker = parts[0].upper()
        company = COMPANY_NAMES.get(ticker, ticker)

        if parts[1] == "10K":
            filing_type = "10-K"
            year = parts[2]
        elif parts[1] == "10Q":
            filing_type = "10-Q"
            year = "latest"
        elif parts[1] == "DEF14A":
            filing_type = "DEF 14A"
            year = "latest"
        else:
            filing_type = parts[1]
            year = parts[2]

        return FilingMetadata(
            source_file=filename,
            company=company,
            ticker=ticker,
            filing_type=filing_type,
            year=year,
        )

    @staticmethod
    def _build_page_map(pages: list[str]) -> list[tuple[int, int, int]]:
        """Create (start, end, page_number) mappings from concatenated text offsets."""
        mapping: list[tuple[int, int, int]] = []
        cursor = 0
        for idx, page in enumerate(pages, start=1):
            start = cursor
            end = cursor + len(page)
            mapping.append((start, end, idx))
            cursor = end + 2
        return mapping

    @staticmethod
    def _estimate_page_number(page_map: list[tuple[int, int, int]], offset: int) -> int:
        """Estimate source page number by character offset in merged text."""
        for start, end, page_number in page_map:
            if start <= offset <= end:
                return page_number
        return page_map[-1][2] if page_map else 1

    def chunk_pdf(self, pdf_path: Path) -> list[ChunkRecord]:
        """Extract and split one filing PDF into chunk records."""
        metadata = self.parse_metadata(pdf_path)
        pages = self.extract_pdf_pages(pdf_path)

        merged_text = "\n\n".join(page for page in pages if page)
        if not merged_text.strip():
            return []

        page_map = self._build_page_map(pages)
        chunks = self.splitter.split_text(merged_text)

        records: list[ChunkRecord] = []
        search_cursor = 0
        for chunk_index, chunk_text in enumerate(chunks):
            found_at = merged_text.find(chunk_text, search_cursor)
            if found_at == -1:
                found_at = merged_text.find(chunk_text)
            if found_at == -1:
                found_at = search_cursor

            page_number = self._estimate_page_number(page_map, found_at)
            search_cursor = found_at + max(1, len(chunk_text) // 2)

            record_meta: dict[str, str | int] = {
                "source_file": metadata.source_file,
                "company": metadata.company,
                "ticker": metadata.ticker,
                "filing_type": metadata.filing_type,
                "year": metadata.year,
                "chunk_index": chunk_index,
                "page_number": page_number,
            }
            records.append(ChunkRecord(chunk_text=chunk_text, metadata=record_meta))

        return records

    def chunk_documents(self, documents_root: Path) -> list[ChunkRecord]:
        """Chunk all PDFs recursively under the documents directory."""
        records: list[ChunkRecord] = []
        for pdf_path in sorted(documents_root.rglob("*.pdf")):
            records.extend(self.chunk_pdf(pdf_path))
        return records
