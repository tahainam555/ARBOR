# SEC Investment Research Voice Assistant

## 1. Project Title & Team Members

- Project: SEC Investment Research Voice Assistant
- Team Members: Add your team names and IDs here

## 2. Business Use Case

Retail investors and financial advisors need fast access to specific facts buried inside long SEC filings. This project combines local RAG retrieval, voice I/O, and finance tools to answer filing-driven questions with citations in real time.

## 3. Architecture Diagram

```text
Browser UI (WebSocket + REST)
        |
        v
FastAPI Server (backend/main.py)
        |
        +--> ConversationManager
              |
              +--> STT (faster-whisper)
              +--> RAG Retriever (ChromaDB + MiniLM)
              +--> Tool Orchestrator
              |      +--> CRM Tool (SQLite)
              |      +--> Stock Tool (yfinance)
              |      +--> Calculator Tool
              |      +--> News Tool (RSS)
              +--> LLM Engine (Ollama HTTP API)
              +--> TTS (edge-tts)
              +--> LatencyTracker (SQLite)
```

## 4. Model Selection

- LLM: Ollama `llama3.2:3b`
- Why: avoids local GGUF loading while keeping the same small-model CPU-friendly footprint
- Embeddings: all-MiniLM-L6-v2 for fast semantic retrieval on CPU

## 5. Voice Pipeline

- STT: faster-whisper base.en with beam_size=1 and VAD enabled
- TTS: edge-tts with sentence-level streaming via WebSocket
- Audio flow: browser MediaRecorder -> server STT -> LLM text stream -> TTS audio chunks

## 6. Document Collection

Target corpus includes 50 filing outputs across:

- AAPL, MSFT, TSLA, AMZN, GOOGL, JPM, JNJ, XOM, WMT, NVDA
- Per ticker: 10-K 2023, 10-K 2022, 10-K 2021, latest 10-Q, DEF 14A

Chunking setup:

- chunk_size=512
- chunk_overlap=50
- splitter: RecursiveCharacterTextSplitter
- vector store: ChromaDB persistent client at chroma_db/

## 7. Tools Description

- crm_tool: user profile CRUD, watchlist updates, interaction logs
- stock_price: live market snapshots with 60s cache
- calculator: ROI, CAGR, compound interest, PE, dividend yield, portfolio, break-even
- news_tool: RSS-based finance news aggregation and deduplication

## 8. Latency Benchmarks

Initial target benchmark table:

| Stage             | Avg (ms) | P95 (ms) |
| ----------------- | -------- | -------- |
| STT Transcription | 312      | 450      |
| RAG Embedding     | 45       | 80       |
| RAG Retrieval     | 89       | 140      |
| Tool Detection    | 120      | 200      |
| LLM First Token   | 1840     | 2400     |
| LLM Full Response | 4230     | 6000     |
| TTS Synthesis     | 520      | 800      |
| End-to-End        | 7156     | 9000     |

## 9. Real-Time Optimizations

- Async WebSocket pipeline with non-blocking stages
- Thread offloading for blocking libraries (yfinance, sentence-transformers, llama.cpp)
- Singleton loading for heavy models (LLM/STT)
- Local caching in stock/news tools
- Persistent ChromaDB and SQLite stores

## 10. Setup Instructions

1. Clone repository.
2. Create venv and install dependencies:
   - Windows: .venv/Scripts/python -m pip install -r requirements.txt
3. Make sure Ollama is running and the model is available:
   - ollama serve
   - ollama pull llama3.2:3b
4. Download filings:
   - python scripts/download_filings.py --user-agent "Your Name email@example.com"
5. Index documents:
   - python scripts/index_documents.py
6. Start server:
   - uvicorn backend.main:app --host 0.0.0.0 --port 8000
7. Open frontend/index.html through a static server or backend host.

Docker:

- docker compose up --build

## 11. Environment Variables

See .env.example for the complete list:

- LLM_BACKEND
- OLLAMA_BASE_URL
- OLLAMA_MODEL
- LLM_MODEL_PATH
- N_THREADS
- N_CTX
- CHROMA_PATH
- DATA_PATH
- DOCUMENTS_PATH
- WHISPER_MODEL
- TTS_VOICE
- TOP_K_CHUNKS
- CHUNK_SIZE
- CHUNK_OVERLAP
- SESSION_TIMEOUT_MINUTES
- MAX_SESSIONS
- LOG_LEVEL

## 12. Known Limitations

- Full 50-document download depends on SEC endpoint availability and user-agent compliance
- Retrieval quality depends on generated PDF normalization for non-PDF SEC sources
- Voice latency varies by local CPU and network conditions for edge-tts

## 13. Demo Video Link

Add your demo video URL here.
