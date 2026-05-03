"""FastAPI application entrypoint for SEC Investment Assistant."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from backend.config import get_settings
from backend.chat_store import ChatStore
from backend.concurrency_limiter import TurnConcurrencyLimiter
from backend.conversation_manager import ConversationManager
from backend.domain_classifier import DomainClassifier
from backend.latency_tracker import LatencyTracker
from backend.llm_engine import LLMEngine
from backend.rag.indexer import SECIndexer
from backend.rag.retriever import RAGRetriever
from backend.session_store import SessionStore
from backend.tool_orchestrator import ToolOrchestrator
from backend.tools.calculator_tool import CalculatorTool
from backend.tools.crm_tool import CRMTool
from backend.tools.news_tool import NewsTool
from backend.tools.stock_price_tool import StockPriceTool
from backend.conversation_manager import EntityMemoryExtractor
from backend.voice.synthesizer import SpeechSynthesizer
from backend.voice.transcriber import AudioTranscriber

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("sec-assistant")

app = FastAPI(title="SEC Investment Research Assistant", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    """Initialize all singleton components and persistent stores."""
    start = time.perf_counter()
    component_times: dict[str, float] = {}

    app.state.model_loaded = False

    t0 = time.perf_counter()
    latency_tracker = LatencyTracker()
    await latency_tracker.initialize()
    component_times["latency_tracker"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    crm_tool = CRMTool()
    await crm_tool.initialize()
    component_times["crm_tool"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    session_store = SessionStore()
    await session_store.initialize()
    component_times["session_store"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    chat_store = ChatStore()
    await chat_store.initialize()
    component_times["chat_store"] = (time.perf_counter() - t0) * 1000.0

    domain_classifier = DomainClassifier()
    component_times["domain_classifier"] = 0.0

    t0 = time.perf_counter()
    retriever = RAGRetriever()
    component_times["retriever"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    transcriber = AudioTranscriber.get_instance()
    component_times["transcriber"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    synthesizer = SpeechSynthesizer()
    component_times["synthesizer"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    llm_engine = LLMEngine.get_instance()
    component_times["llm_engine"] = (time.perf_counter() - t0) * 1000.0
    app.state.model_loaded = True

    tools = [
        crm_tool,
        StockPriceTool(),
        CalculatorTool(),
        NewsTool(),
    ]
    orchestrator = ToolOrchestrator(
        tools,
        llm_intent_detector=llm_engine.generate_full,
    )

    app.state.latency_tracker = latency_tracker
    app.state.crm_tool = crm_tool
    app.state.session_store = session_store
    app.state.chat_store = chat_store
    app.state.retriever = retriever
    app.state.transcriber = transcriber
    app.state.synthesizer = synthesizer
    app.state.llm_engine = llm_engine
    app.state.orchestrator = orchestrator
    app.state.indexer = SECIndexer()
    app.state.manager = ConversationManager(
        llm_engine=llm_engine,
        retriever=retriever,
        tool_orchestrator=orchestrator,
        transcriber=transcriber,
        synthesizer=synthesizer,
        latency_tracker=latency_tracker,
        crm_tool=crm_tool,
        session_store=session_store,
        chat_store=chat_store,
        domain_classifier=domain_classifier,
    )
    app.state.turn_limiter = TurnConcurrencyLimiter(
        max_concurrent=settings.max_concurrent_turns,
        queue_timeout_seconds=settings.turn_queue_timeout_seconds,
    )

    async def _cleanup_loop() -> None:
        while True:
            try:
                await asyncio.sleep(300)
                await app.state.manager.session_manager.cleanup_expired()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Session cleanup loop failed")

    app.state.session_cleanup_task = asyncio.create_task(_cleanup_loop())

    async def _run_warmup(name: str, coro: Any) -> tuple[str, float, str | None]:
        warmup_start = time.perf_counter()
        try:
            await coro
            return name, (time.perf_counter() - warmup_start) * 1000.0, None
        except Exception as exc:  # noqa: BLE001
            return name, (time.perf_counter() - warmup_start) * 1000.0, str(exc)

    async def _warmup_background() -> None:
        warmup_results = await asyncio.gather(
            _run_warmup("retriever", retriever.warmup()),
            _run_warmup("transcriber", transcriber.warmup()),
            _run_warmup("llm_engine", llm_engine.warmup()),
        )

        for name, duration_ms, error in warmup_results:
            component_times[f"warmup_{name}"] = duration_ms
            if error:
                logger.warning("Warmup failed for %s: %s", name, error)

        logger.info("Warmups complete")

    app.state.warmup_task = asyncio.create_task(_warmup_background())

    total_ms = (time.perf_counter() - start) * 1000.0
    logger.info("System ready")
    logger.info("Startup component timings (ms): %s", component_times)
    logger.info("Total startup time (ms): %.2f", total_ms)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    task = getattr(app.state, "session_cleanup_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@app.get("/", include_in_schema=False)
async def root() -> dict[str, Any]:
    """Simple root endpoint for browser sanity checks."""
    return {
        "status": "ok",
        "service": "SEC Investment Research Assistant backend",
        "health": "/health",
        "docs": "/docs",
        "websocket": "/ws/{session_id}",
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """Avoid noisy 404 logs for browser favicon requests."""
    return Response(status_code=204)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health endpoint with model and index visibility."""
    indexer: SECIndexer = app.state.indexer
    docs = await asyncio.to_thread(indexer.get_indexed_documents)
    return {
        "status": "ok",
        "model_loaded": bool(getattr(app.state, "model_loaded", False)),
        "docs_indexed": len(docs),
    }


@app.get("/api/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    """List active conversation sessions."""
    session_store: SessionStore = app.state.session_store
    return await session_store.list_sessions()


@app.post("/api/sessions")
async def create_session(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create or refresh one session record."""
    session_store: SessionStore = app.state.session_store
    payload = payload or {}
    session_id = str(payload.get("session_id") or uuid.uuid4())
    user_id = payload.get("user_id")
    title = payload.get("title")
    session = await session_store.create_session(session_id=session_id, user_id=user_id, title=title)
    await session_store.touch_session(session_id=session_id, user_id=user_id, title=title, turn_count=session["turn_count"])
    return await session_store.get_session(session_id) or session


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Return one stored session record."""
    session_store: SessionStore = app.state.session_store
    session = await session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.get("/api/sessions/{session_id}/history")
async def get_session_history(session_id: str) -> dict[str, Any]:
    """Return one session with its persisted message history."""
    session_store: SessionStore = app.state.session_store
    chat_store: ChatStore = app.state.chat_store
    session = await session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    history = await chat_store.get_history(session_id, limit=100)
    return {"session": session, "messages": history}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    """Delete a session and its chat history."""
    session_store: SessionStore = app.state.session_store
    chat_store: ChatStore = app.state.chat_store
    await chat_store.delete_session_messages(session_id)
    await session_store.delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}


@app.post("/api/sessions/{session_id}/summary/refresh")
async def refresh_session_summary(session_id: str) -> dict[str, Any]:
    """Force-refresh and return the latest summary for one session."""
    manager: ConversationManager = app.state.manager
    return manager.get_active_sessions()


@app.get("/api/latency/{session_id}")
async def get_session_latency(session_id: str) -> dict[str, Any]:
    """Return full latency payload for one session."""
    tracker: LatencyTracker = app.state.latency_tracker
    return await tracker.get_session_latency_payload(session_id)


@app.get("/api/latency/global")
async def get_global_latency() -> dict[str, Any]:
    """Return global per-stage average latencies."""
    tracker: LatencyTracker = app.state.latency_tracker
    return {"averages": await tracker.get_global_averages()}


@app.get("/api/documents")
async def list_documents() -> dict[str, Any]:
    """List indexed documents and chunk counts."""
    indexer: SECIndexer = app.state.indexer
    docs = await asyncio.to_thread(indexer.get_indexed_documents)
    return {
        "documents": [{"source_file": source, "chunk_count": count} for source, count in sorted(docs.items())],
        "count": len(docs),
    }


@app.get("/api/rag/retrieve")
async def rag_retrieve(query: str, top_k: int = 5, filter_ticker: str | None = None) -> dict[str, Any]:
    """Expose RAG retrieval for evaluation and debugging."""
    retriever: RAGRetriever = app.state.retriever
    chunks = await retriever.retrieve(query, top_k=top_k, filter_ticker=filter_ticker)
    return {
        "chunks": [
            {
                "id": chunk.id,
                "text": chunk.text,
                "score": chunk.score,
                "metadata": {
                    "source_file": chunk.source,
                    "company": chunk.company,
                    "ticker": chunk.ticker,
                    "filing_type": chunk.filing_type,
                    "year": chunk.year,
                    "chunk_index": chunk.chunk_index,
                },
            }
            for chunk in chunks
        ]
    }


@app.post("/api/crm/user")
async def create_crm_user(body: dict[str, Any]) -> dict[str, Any]:
    crm_tool: CRMTool = app.state.crm_tool
    user_id = str(body.get("user_id", "")).strip()
    name = str(body.get("name", "Investor")).strip() or "Investor"
    user = await crm_tool.create_user(user_id=user_id, name=name)
    return user


@app.get("/api/crm/user/{user_id}")
async def get_crm_user(user_id: str) -> dict[str, Any]:
    crm_tool: CRMTool = app.state.crm_tool
    user = await crm_tool.get_user(user_id)
    if user is None:
        return Response(status_code=404)
    return user


@app.patch("/api/crm/user/{user_id}")
async def update_crm_user(user_id: str, body: dict[str, Any]) -> dict[str, Any]:
    crm_tool: CRMTool = app.state.crm_tool
    field = str(body.get("field", "")).strip()
    value = body.get("value")
    ok = await crm_tool.update_field(user_id=user_id, field=field, value=value)
    return {"success": ok, "user_id": user_id, "field": field}


@app.post("/api/crm/user/{user_id}/watchlist")
async def add_to_watchlist(user_id: str, body: dict[str, Any]) -> dict[str, Any]:
    crm_tool: CRMTool = app.state.crm_tool
    ticker = str(body.get("ticker", "")).strip()
    ok = await crm_tool.add_to_watchlist(user_id=user_id, ticker=ticker)
    return {"success": ok, "user_id": user_id, "ticker": ticker.upper()}


@app.get("/api/tools/stock_price")
async def eval_stock_price(ticker: str) -> dict[str, Any]:
    orchestrator: ToolOrchestrator = app.state.orchestrator
    result = await orchestrator.tools["stock_price"].execute(ticker=ticker)
    return {"success": result.success, **result.data, "error": result.error}


@app.post("/api/tools/calculator")
async def eval_calculator(body: dict[str, Any]) -> dict[str, Any]:
    orchestrator: ToolOrchestrator = app.state.orchestrator
    calc_type = str(body.get("calculation_type", "")).strip()
    params = body.get("params")
    if not isinstance(params, dict):
        params = {k: v for k, v in body.items() if k != "calculation_type"}
    result = await orchestrator.tools["calculator"].execute(calculation_type=calc_type, params=params)
    return {"success": result.success, **result.data, "error": result.error}


@app.get("/api/tools/news")
async def eval_news(query: str, max_results: int = 5) -> dict[str, Any]:
    orchestrator: ToolOrchestrator = app.state.orchestrator
    result = await orchestrator.tools["news_tool"].execute(query=query, max_results=max_results)
    return {"success": result.success, **result.data, "error": result.error, "cache_age_seconds": 0}


@app.post("/api/test/transcribe")
async def test_transcribe(body: dict[str, Any]) -> dict[str, Any]:
    transcriber: AudioTranscriber = app.state.transcriber
    audio_b64 = str(body.get("audio", ""))
    audio_bytes = base64.b64decode(audio_b64)
    text, duration_ms = await transcriber.transcribe(audio_bytes, format_hint=str(body.get("format", body.get("audio_format", ""))))
    return {"transcription": text, "duration_ms": duration_ms}


@app.post("/api/test/synthesize")
async def test_synthesize(body: dict[str, Any]) -> dict[str, Any]:
    synthesizer: SpeechSynthesizer = app.state.synthesizer
    audio_bytes, duration_ms = await synthesizer.synthesize_full(str(body.get("text", "")))
    return {
        "success": True,
        "audio_bytes_b64": base64.b64encode(audio_bytes).decode(),
        "duration_ms": duration_ms,
    }


@app.post("/api/test/entity_extract")
async def test_entity_extract(body: dict[str, Any]) -> dict[str, Any]:
    extractor = EntityMemoryExtractor()
    extracted = extractor.extract(
        str(body.get("user_message", "")),
        str(body.get("assistant_response", "")),
        {},
    )
    return {"extracted": extracted}


@app.post("/api/index")
async def trigger_indexing() -> dict[str, Any]:
    """Re-run indexing pipeline and return summary metrics."""
    indexer: SECIndexer = app.state.indexer
    summary = await asyncio.to_thread(indexer.index_documents)
    return {
        "indexed_documents": summary.indexed_documents,
        "skipped_documents": summary.skipped_documents,
        "failed_documents": summary.failed_documents,
        "indexed_chunks": summary.indexed_chunks,
    }


@app.get("/api/metrics/concurrency")
async def get_concurrency_metrics() -> dict[str, Any]:
    """Return current concurrency limiter state and metrics."""
    limiter: TurnConcurrencyLimiter = app.state.turn_limiter
    metrics = limiter.get_metrics()
    return {
        "max_concurrent_turns": metrics.max_concurrent_turns,
        "current_active_turns": metrics.current_active_turns,
        "queued_sessions": metrics.queued_sessions,
        "total_turns_processed": metrics.total_turns_processed,
        "total_wait_ms": metrics.total_wait_ms,
    }


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Main real-time conversation websocket for text and voice messages."""
    await websocket.accept()
    manager: ConversationManager = app.state.manager
    limiter: TurnConcurrencyLimiter = app.state.turn_limiter

    try:
        while True:
            payload = await websocket.receive_json()
            try:
                msg_type = payload.get("type")

                if msg_type == "text_input":
                    message = str(payload.get("message", "")).strip()
                    breakdown = await manager.handle_text_turn(
                        session_id=session_id,
                        message=message,
                        websocket=websocket,
                        speak_response=False,
                    )
                    await websocket.send_json(
                        {
                            "type": "turn_complete",
                            "turn_id": breakdown["turn_id"],
                            "latency_breakdown": breakdown.get("stages", {}),
                        }
                    )
                    continue

                if msg_type == "audio_input":
                    encoded = payload.get("audio", "")
                    if not encoded:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "Missing audio payload",
                                "recoverable": True,
                            }
                        )
                        continue

                    try:
                        audio_bytes = base64.b64decode(encoded, validate=True)
                    except Exception:  # noqa: BLE001
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "Invalid base64 audio payload",
                                "recoverable": True,
                            }
                        )
                        continue

                    audio_format = str(payload.get("format", "")).strip().lower() or None
                    breakdown = await manager.handle_audio_turn(
                        session_id=session_id,
                        audio_bytes=audio_bytes,
                        websocket=websocket,
                        audio_format=audio_format,
                    )
                    await websocket.send_json(
                        {
                            "type": "turn_complete",
                            "turn_id": breakdown["turn_id"],
                            "latency_breakdown": breakdown.get("stages", {}),
                        }
                    )
                    continue

                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"Unsupported message type: {msg_type}",
                        "recoverable": True,
                    }
                )
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected for session=%s", session_id)
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception("WebSocket message error for session=%s", session_id)
                try:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": f"Server error: {exc}",
                            "recoverable": True,
                        }
                    )
                except Exception:  # noqa: BLE001
                    logger.info("Unable to send error payload, websocket likely closed for session=%s", session_id)
                    break
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session=%s", session_id)
    except Exception:  # noqa: BLE001
        logger.exception("WebSocket error for session=%s", session_id)
