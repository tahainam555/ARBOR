"""Download SEC filings for target companies and store them as PDF files.

This script fetches filing metadata from SEC submissions endpoints, downloads
filing content, converts text content into searchable PDFs, and saves the output
into the required folder/file naming structure.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import get_settings

SEC_BASE = "https://www.sec.gov"
SEC_DATA_BASE = "https://data.sec.gov"
REQUEST_TIMEOUT_SECONDS = 45.0
MAX_CONCURRENT_DOWNLOADS = 3


@dataclass(frozen=True)
class Company:
    """Target company metadata needed for SEC submissions API requests."""

    ticker: str
    company: str
    cik: str


@dataclass(frozen=True)
class FilingTarget:
    """Represents one required filing output for a company."""

    output_name: str
    form_type: str
    year: str | None = None


@dataclass
class FilingRecord:
    """Normalized filing entry from SEC submissions metadata."""

    form: str
    accession_number: str
    primary_document: str
    filing_date: str
    report_date: str | None


COMPANIES: list[Company] = [
    Company("AAPL", "Apple Inc.", "0000320193"),
    Company("MSFT", "Microsoft Corporation", "0000789019"),
    Company("TSLA", "Tesla, Inc.", "0001318605"),
    Company("AMZN", "Amazon.com, Inc.", "0001018724"),
    Company("GOOGL", "Alphabet Inc.", "0001652044"),
    Company("JPM", "JPMorgan Chase & Co.", "0000019617"),
    Company("JNJ", "Johnson & Johnson", "0000200406"),
    Company("XOM", "Exxon Mobil Corporation", "0000034088"),
    Company("WMT", "Walmart Inc.", "0000104169"),
    Company("NVDA", "NVIDIA Corporation", "0001045810"),
]

REQUIRED_FILINGS: list[FilingTarget] = [
    FilingTarget("{ticker}_10K_2023.pdf", "10-K", "2023"),
    FilingTarget("{ticker}_10K_2022.pdf", "10-K", "2022"),
    FilingTarget("{ticker}_10K_2021.pdf", "10-K", "2021"),
    FilingTarget("{ticker}_10Q_latest.pdf", "10-Q", None),
    FilingTarget("{ticker}_DEF14A.pdf", "DEF 14A", None),
]


def build_headers(user_agent: str) -> dict[str, str]:
    """Return SEC-compliant headers for all outbound requests."""
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }


def strip_html_tags(raw: str) -> str:
    """Convert raw HTML content to readable plain text."""
    text = re.sub(r"<script[\\s\\S]*?</script>", " ", raw, flags=re.IGNORECASE)
    text = re.sub(r"<style[\\s\\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\\s+", " ", text)
    return text.strip()


def write_text_pdf(output_path: Path, title: str, body_text: str) -> None:
    """Create a searchable PDF from plain text using PyMuPDF."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open()
    page = doc.new_page()
    y = 48.0
    line_height = 13.0
    max_width = 540.0

    page.insert_text((50.0, y), title, fontsize=14)
    y += 24.0

    paragraphs = [p.strip() for p in re.split(r"(?<=[.!?])\\s+", body_text) if p.strip()]
    current_page = page

    for paragraph in paragraphs:
        words = paragraph.split(" ")
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            width = fitz.get_text_length(candidate, fontsize=10)
            if width <= max_width:
                line = candidate
            else:
                if y > 780.0:
                    current_page = doc.new_page()
                    y = 48.0
                current_page.insert_text((50.0, y), line, fontsize=10)
                y += line_height
                line = word
        if line:
            if y > 780.0:
                current_page = doc.new_page()
                y = 48.0
            current_page.insert_text((50.0, y), line, fontsize=10)
            y += line_height

    doc.save(output_path)
    doc.close()


def parse_recent_filings(payload: dict[str, Any]) -> list[FilingRecord]:
    """Extract filing records from SEC submissions JSON payload."""
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])

    count = min(len(forms), len(accessions), len(primary_docs), len(filing_dates))
    records: list[FilingRecord] = []
    for idx in range(count):
        records.append(
            FilingRecord(
                form=forms[idx],
                accession_number=accessions[idx],
                primary_document=primary_docs[idx],
                filing_date=filing_dates[idx],
                report_date=report_dates[idx] if idx < len(report_dates) else None,
            )
        )
    return records


async def fetch_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    """Download a JSON payload and return parsed data."""
    response = await client.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


async def get_all_filing_records(client: httpx.AsyncClient, cik: str) -> list[FilingRecord]:
    """Collect filings from recent and historical SEC submissions data."""
    main_url = f"{SEC_DATA_BASE}/submissions/CIK{cik}.json"
    payload = await fetch_json(client, main_url)

    records = parse_recent_filings(payload)
    historical_files = payload.get("filings", {}).get("files", [])

    for item in historical_files:
        name = item.get("name")
        if not name:
            continue
        history_url = f"{SEC_DATA_BASE}/submissions/{name}"
        try:
            history_payload = await fetch_json(client, history_url)
            records.extend(parse_recent_filings({"filings": {"recent": history_payload}}))
        except httpx.HTTPError:
            logging.warning("Failed to fetch historical submissions file: %s", history_url)

    unique: dict[tuple[str, str], FilingRecord] = {}
    for rec in records:
        key = (rec.form, rec.accession_number)
        unique[key] = rec

    return list(unique.values())


def select_filing(records: list[FilingRecord], target: FilingTarget) -> FilingRecord | None:
    """Select best filing record for a target requirement."""
    matching = [r for r in records if r.form == target.form_type]
    if not matching:
        return None

    if target.year is not None:
        year_filtered = [
            r
            for r in matching
            if ((r.report_date or "").startswith(target.year) or r.filing_date.startswith(target.year))
        ]
        if not year_filtered:
            return None
        return sorted(year_filtered, key=lambda x: x.filing_date, reverse=True)[0]

    return sorted(matching, key=lambda x: x.filing_date, reverse=True)[0]


async def download_filing_text(
    client: httpx.AsyncClient,
    cik: str,
    record: FilingRecord,
) -> str:
    """Download filing content and return clean text."""
    accession_no_dash = record.accession_number.replace("-", "")
    cik_trimmed = str(int(cik))
    primary_doc = record.primary_document

    filing_url = f"{SEC_BASE}/Archives/edgar/data/{cik_trimmed}/{accession_no_dash}/{primary_doc}"

    response = await client.get(filing_url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()
    if "pdf" in content_type or primary_doc.lower().endswith(".pdf"):
        # Save PDF content by extracting text first for normalized searchable output.
        temp_doc = fitz.open(stream=response.content, filetype="pdf")
        chunks = [page.get_text("text") for page in temp_doc]
        temp_doc.close()
        text = "\n".join(chunks)
    else:
        text = strip_html_tags(response.text)

    if not text:
        raise ValueError(f"No extractable text found for filing: {filing_url}")

    return text


async def process_company(
    client: httpx.AsyncClient,
    documents_root: Path,
    company: Company,
) -> tuple[int, int]:
    """Download and persist all required filings for one company.

    Returns:
        tuple[int, int]: (downloaded_count, missing_count)
    """
    records = await get_all_filing_records(client, company.cik)

    downloaded = 0
    missing = 0
    company_dir = documents_root / company.ticker
    company_dir.mkdir(parents=True, exist_ok=True)

    for target in REQUIRED_FILINGS:
        picked = select_filing(records, target)
        output_name = target.output_name.format(ticker=company.ticker)
        output_path = company_dir / output_name

        if picked is None:
            logging.warning("Missing filing for %s: %s", company.ticker, output_name)
            missing += 1
            continue

        try:
            text = await download_filing_text(client, company.cik, picked)
            title = f"{company.ticker} {picked.form} ({picked.filing_date})"
            write_text_pdf(output_path, title, text)
            downloaded += 1
            logging.info("Saved %s", output_path.name)
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            logging.error("Failed %s %s: %s", company.ticker, output_name, exc)
            missing += 1

        await asyncio.sleep(0.2)

    return downloaded, missing


async def run_downloads(user_agent: str, docs_path: Path) -> None:
    """Run full download workflow for all target companies."""
    docs_path.mkdir(parents=True, exist_ok=True)
    headers = build_headers(user_agent)

    transport = httpx.AsyncHTTPTransport(retries=3)
    async with httpx.AsyncClient(headers=headers, transport=transport, follow_redirects=True) as client:
        total_downloaded = 0
        total_missing = 0

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

        async def wrapped(company: Company) -> tuple[str, int, int]:
            async with semaphore:
                downloaded, missing = await process_company(client, docs_path, company)
                return company.ticker, downloaded, missing

        tasks = [wrapped(company) for company in COMPANIES]
        results = await asyncio.gather(*tasks)

        for ticker, downloaded, missing in results:
            total_downloaded += downloaded
            total_missing += missing
            logging.info("%s summary: downloaded=%s missing=%s", ticker, downloaded, missing)

    logging.info(
        "Download complete: total_downloaded=%s total_missing=%s expected=%s",
        total_downloaded,
        total_missing,
        len(COMPANIES) * len(REQUIRED_FILINGS),
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Download SEC filings as normalized PDFs")
    parser.add_argument(
        "--user-agent",
        required=True,
        help="SEC-compliant user agent, e.g. 'Your Name email@example.com'",
    )
    parser.add_argument(
        "--documents-path",
        default=None,
        help="Override documents directory path (defaults to configured DOCUMENTS_PATH)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    return parser.parse_args()


def main() -> None:
    """Script entrypoint."""
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    settings = get_settings()
    docs_path = Path(args.documents_path).resolve() if args.documents_path else settings.documents_dir

    start_time = datetime.now()
    logging.info("Starting SEC filings download into %s", docs_path)

    asyncio.run(run_downloads(user_agent=args.user_agent, docs_path=docs_path))

    elapsed = datetime.now() - start_time
    logging.info("Finished in %s", elapsed)


if __name__ == "__main__":
    main()
