"""FastAPI application entrypoint for SEC Investment Assistant."""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.conversation_manager import ConversationManager
from backend.latency_tracker import LatencyTracker
from backend.llm_engine import LLMEngine
from backend.rag.indexer import SECIndexer
from backend.rag.retriever import RAGRetriever
from backend.tool_orchestrator import ToolOrchestrator
from backend.tools.calculator_tool import CalculatorTool
from backend.tools.crm_tool import CRMTool
from backend.tools.news_tool import NewsTool
from backend.tools.stock_price_tool import StockPriceTool
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
    orchestrator = ToolOrchestrator(tools)

    app.state.latency_tracker = latency_tracker
    app.state.crm_tool = crm_tool
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
    )

    total_ms = (time.perf_counter() - start) * 1000.0
    logger.info("System ready")
    logger.info("Startup component timings (ms): %s", component_times)
    logger.info("Total startup time (ms): %.2f", total_ms)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health endpoint with model and index visibility."""
    indexer: SECIndexer = app.state.indexer
    docs = indexer.get_indexed_documents()
    return {
        "status": "ok",
        "model_loaded": bool(getattr(app.state, "model_loaded", False)),
        "docs_indexed": len(docs),
    }


@app.get("/api/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    """List active conversation sessions."""
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
    docs = indexer.get_indexed_documents()
    return {
        "documents": [{"source_file": source, "chunk_count": count} for source, count in sorted(docs.items())],
        "count": len(docs),
    }


@app.post("/api/index")
async def trigger_indexing() -> dict[str, Any]:
    """Re-run indexing pipeline and return summary metrics."""
    indexer: SECIndexer = app.state.indexer
    summary = indexer.index_documents()
    return {
        "indexed_documents": summary.indexed_documents,
        "skipped_documents": summary.skipped_documents,
        "failed_documents": summary.failed_documents,
        "indexed_chunks": summary.indexed_chunks,
    }


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Main real-time conversation websocket for text and voice messages."""
    await websocket.accept()
    manager: ConversationManager = app.state.manager

    try:
        while True:
            payload = await websocket.receive_json()
            msg_type = payload.get("type")

            if msg_type == "text_input":
                message = str(payload.get("message", "")).strip()
                breakdown = await manager.handle_text_turn(
                    session_id=session_id,
                    message=message,
                    websocket=websocket,
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

                audio_bytes = base64.b64decode(encoded)
                breakdown = await manager.handle_audio_turn(
                    session_id=session_id,
                    audio_bytes=audio_bytes,
                    websocket=websocket,
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
    except Exception as exc:  # noqa: BLE001
        logger.exception("WebSocket error for session=%s", session_id)
        await websocket.send_json(
            {
                "type": "error",
                "message": f"Server error: {exc}",
                "recoverable": True,
            }
        )
