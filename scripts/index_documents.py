"""CLI entrypoint to index SEC filing PDFs into ChromaDB."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.rag.indexer import SECIndexer


def parse_args() -> argparse.Namespace:
    """Parse indexer CLI arguments."""
    parser = argparse.ArgumentParser(description="Index SEC filing documents into ChromaDB")
    parser.add_argument(
        "--documents-path",
        default=None,
        help="Optional override path for documents directory",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def main() -> None:
    """Run indexing pipeline and print summary metrics."""
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s | %(levelname)s | %(message)s")

    indexer = SECIndexer()
    docs_path = Path(args.documents_path).resolve() if args.documents_path else None
    summary = indexer.index_documents(documents_path=docs_path)

    print(f"Indexed documents: {summary.indexed_documents}")
    print(f"Skipped documents: {summary.skipped_documents}")
    print(f"Failed documents: {summary.failed_documents}")
    print(f"Indexed chunks: {summary.indexed_chunks}")


if __name__ == "__main__":
    main()
