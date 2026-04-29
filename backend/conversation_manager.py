"""Conversation orchestration pipeline for text and voice turns."""

from __future__ import annotations

import asyncio
import base64
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from backend.config import get_settings
from backend.chat_store import ChatStore
from backend.domain_classifier import DomainClassifier
from backend.error_recovery import build_recoverable_error_payload
from backend.latency_tracker import LatencyTracker
from backend.llm_engine import LLMEngine
from backend.session_store import SessionStore
from backend.summarizer import ConversationSummarizer
from backend.tool_orchestrator import ToolOrchestrator
from backend.tools.crm_tool import CRMTool
from backend.voice.synthesizer import SpeechSynthesizer
from backend.voice.transcriber import AudioTranscriber

if TYPE_CHECKING:
    from backend.rag.retriever import RAGRetriever, RetrievedChunk


SYSTEM_PROMPT = (
    "You are an expert SEC investment research assistant. Answer questions using the provided "
    "SEC filing excerpts. Be precise with numbers. Cite your sources (e.g., 'According to Apple's "
    "2023 10-K...'). If information is not in the provided context, say so clearly."
)


@dataclass
class ConversationSession:
    """In-memory state for one active user conversation."""

    session_id: str
    user_id: str | None = None
    running_summary: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    turn_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AudioRecordingWebSocket:
    """Forward websocket payloads while collecting TTS chunks for replay."""

    def __init__(self, websocket: Any) -> None:
        self.websocket = websocket
        self.audio_chunks: list[str] = []
        self.mime_type = "audio/mpeg"

    async def send_json(self, payload: dict[str, Any]) -> None:
        if payload.get("type") == "audio_chunk":
            audio = payload.get("audio")
            if isinstance(audio, str) and audio:
                self.audio_chunks.append(audio)
            mime_type = payload.get("mime_type")
            if isinstance(mime_type, str) and mime_type:
                self.mime_type = mime_type
        await self.websocket.send_json(payload)

    def combined_audio_base64(self) -> str:
        """Return one base64 blob from collected per-chunk audio payloads."""
        if not self.audio_chunks:
            return ""

        combined = bytearray()
        for chunk in self.audio_chunks:
            try:
                combined.extend(base64.b64decode(chunk))
            except Exception:  # noqa: BLE001
                continue
        return base64.b64encode(bytes(combined)).decode("ascii") if combined else ""


class ConversationManager:
    """Coordinates STT, RAG, tools, LLM generation, TTS, and latency logging."""

    def __init__(
        self,
        llm_engine: LLMEngine,
        retriever: RAGRetriever,
        tool_orchestrator: ToolOrchestrator,
        transcriber: AudioTranscriber,
        synthesizer: SpeechSynthesizer,
        latency_tracker: LatencyTracker,
        crm_tool: CRMTool,
        session_store: SessionStore | None = None,
        chat_store: ChatStore | None = None,
        domain_classifier: DomainClassifier | None = None,
        summarizer: ConversationSummarizer | None = None,
    ) -> None:
        self.settings = get_settings()
        self.llm_engine = llm_engine
        self.retriever = retriever
        self.tool_orchestrator = tool_orchestrator
        self.transcriber = transcriber
        self.synthesizer = synthesizer
        self.latency_tracker = latency_tracker
        self.crm_tool = crm_tool
        self.session_store = session_store or SessionStore()
        self.chat_store = chat_store or ChatStore()
        self.domain_classifier = domain_classifier or DomainClassifier()
        self.summarizer = summarizer or ConversationSummarizer()
        self.sessions: dict[str, ConversationSession] = {}

    def _cleanup_sessions(self) -> None:
        """Expire old sessions and enforce max concurrent sessions cap."""
        now = datetime.now(timezone.utc)
        timeout = timedelta(minutes=self.settings.session_timeout_minutes)

        expired_ids = [
            sid
            for sid, session in self.sessions.items()
            if now - session.last_activity > timeout
        ]
        for sid in expired_ids:
            self.sessions.pop(sid, None)

        if len(self.sessions) <= self.settings.max_sessions:
            return

        oldest = sorted(self.sessions.values(), key=lambda s: s.last_activity)
        overflow = len(self.sessions) - self.settings.max_sessions
        for victim in oldest[:overflow]:
            self.sessions.pop(victim.session_id, None)

    def _get_or_create_session(self, session_id: str) -> ConversationSession:
        """Get session state or initialize a new one."""
        self._cleanup_sessions()
        if session_id not in self.sessions:
            self.sessions[session_id] = ConversationSession(session_id=session_id)

        session = self.sessions[session_id]
        session.last_activity = datetime.now(timezone.utc)
        return session

    async def _load_or_create_session(self, session_id: str) -> ConversationSession:
        """Load session state from SQLite, falling back to a fresh session."""
        self._cleanup_sessions()
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session.last_activity = datetime.now(timezone.utc)
            await self.session_store.touch_session(session_id, user_id=session.user_id, turn_count=session.turn_count)
            return session

        stored = await self.session_store.get_session(session_id)
        if stored is None:
            stored = await self.session_store.create_session(session_id=session_id)

        history = await self.chat_store.get_history(session_id, limit=12)
        created_at = datetime.fromisoformat(stored["created_at"])
        last_activity = datetime.fromisoformat(stored["last_activity"])
        session = ConversationSession(
            session_id=session_id,
            user_id=stored.get("user_id"),
            running_summary=stored.get("summary"),
            history=[{"role": item["role"], "content": item["content"]} for item in history],
            turn_count=int(stored.get("turn_count", 0)),
            created_at=created_at,
            last_activity=last_activity,
        )
        self.sessions[session_id] = session
        await self.session_store.touch_session(session_id, user_id=session.user_id, turn_count=session.turn_count)
        return session

    @staticmethod
    def _truncate_history(history: list[dict[str, str]], max_turns: int = 6) -> list[dict[str, str]]:
        """Keep only most recent N messages from running history."""
        return history[-max_turns:]

    async def _load_crm_context(self, session: ConversationSession) -> str:
        """Build lightweight CRM context text for prompt injection."""
        if not session.user_id:
            return "No user profile loaded."

        user = await self.crm_tool.get_user(session.user_id)
        if not user:
            return "No user profile loaded."

        return (
            f"User ID: {user.get('user_id')}\n"
            f"Name: {user.get('name')}\n"
            f"Risk Profile: {user.get('risk_profile')}\n"
            f"Investment Goals: {user.get('investment_goals')}\n"
            f"Watchlist: {user.get('watchlist')}"
        )

    @staticmethod
    def _format_history(history: list[dict[str, str]]) -> str:
        """Serialize chat history into compact prompt context."""
        lines: list[str] = []
        for item in history:
            role = item.get("role", "user")
            content = item.get("content", "")
            lines.append(f"{role.upper()}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _truncate_text_by_token_estimate(text: str, max_tokens: int) -> str:
        """Trim overly long context strings using a lightweight token estimate."""
        if max_tokens <= 0:
            return ""

        words = text.split()
        max_words = max(1, int(max_tokens / 1.3))
        if len(words) <= max_words:
            return text
        return " ".join(words[-max_words:])

    async def _retrieve_chunks(
        self,
        session_id: str,
        turn_id: int,
        message: str,
    ) -> list[RetrievedChunk]:
        """Run two-stage retrieval timing: embedding then vector search."""
        embedding_start = time.perf_counter()
        embedding = await self.retriever._embed_query(message)
        await self.latency_tracker.log(
            session_id=session_id,
            turn_id=turn_id,
            stage="rag_embedding",
            duration_ms=(time.perf_counter() - embedding_start) * 1000.0,
            metadata={"query_chars": len(message)},
        )

        retrieval_start = time.perf_counter()
        chunks = await self.retriever.retrieve_with_embedding(
            query_embedding=embedding,
            top_k=self.settings.top_k_chunks,
        )
        await self.latency_tracker.log(
            session_id=session_id,
            turn_id=turn_id,
            stage="rag_retrieval",
            duration_ms=(time.perf_counter() - retrieval_start) * 1000.0,
            metadata={"chunks_retrieved": len(chunks)},
        )

        return chunks

    async def _run_tools(
        self,
        session_id: str,
        turn_id: int,
        message: str,
    ) -> tuple[str, dict[str, Any]]:
        """Detect/execute tools and emit per-tool latency logs."""
        async with self.latency_tracker.measure(session_id, turn_id, "tool_detection"):
            tool_result = await self.tool_orchestrator.detect_and_execute(
                message=message,
                session_id=session_id,
            )

        for tool_name, result in tool_result.results.items():
            duration_ms = float(result.get("duration_ms", 0.0))
            await self.latency_tracker.log(
                session_id=session_id,
                turn_id=turn_id,
                stage=f"tool_execution_{tool_name}",
                duration_ms=duration_ms,
                metadata={"success": result.get("success", False)},
            )

        return tool_result.formatted_context, tool_result.results

    async def _build_prompt(
        self,
        user_message: str,
        crm_context: str,
        rag_context: str,
        tool_context: str,
        session_summary: str | None,
        history: list[dict[str, str]],
    ) -> str:
        """Build strict llama-3.2 instruct prompt format."""
        history_text = self._format_history(self._truncate_history(history, max_turns=4))
        history_text = self._truncate_text_by_token_estimate(history_text, max_tokens=350)
        rag_context = self._truncate_text_by_token_estimate(rag_context, max_tokens=2000)
        tool_context = self._truncate_text_by_token_estimate(tool_context, max_tokens=500)
        summary_context = self._truncate_text_by_token_estimate(session_summary or "No prior session summary.", max_tokens=450)

        prompt = (
            "<|begin_of_text|>\n"
            "<|start_header_id|>system<|end_header_id|>\n"
            f"{SYSTEM_PROMPT}\n\n"
            "USER PROFILE:\n"
            f"{crm_context}\n\n"
            "RETRIEVED FILING EXCERPTS:\n"
            f"{rag_context}\n\n"
            "TOOL RESULTS:\n"
            f"{tool_context}\n\n"
            "SESSION SUMMARY:\n"
            f"{summary_context}\n\n"
            "RECENT HISTORY:\n"
            f"{history_text}\n"
            "<|eot_id|>\n"
            "<|start_header_id|>user<|end_header_id|>\n"
            f"{user_message}\n"
            "<|eot_id|>\n"
            "<|start_header_id|>assistant<|end_header_id|>\n"
        )
        return prompt

    @staticmethod
    def _is_generic_title(title: str | None) -> bool:
        """Return whether a session title still looks like a placeholder."""
        if not title:
            return True
        normalized = title.strip().lower()
        return normalized in {"conversation", "new conversation"} or normalized.startswith("conversation ")

    async def _maybe_update_title(self, session: ConversationSession, message: str) -> None:
        """Persist a concise title from the first meaningful request."""
        stored = await self.session_store.get_session(session.session_id)
        if stored is None or not self._is_generic_title(stored.get("title")):
            return

        title = self.summarizer.generate_title(message)
        if self._is_generic_title(title):
            return
        await self.session_store.update_title(session.session_id, title)

    async def _ensure_summary_before_prompt(self, session: ConversationSession) -> None:
        """Refresh compact context before generation for longer conversations."""
        if session.turn_count < 3:
            return

        history_rows = await self.chat_store.get_history(session.session_id, limit=40)
        if len(history_rows) <= 8 and session.running_summary:
            return

        older_rows = history_rows[:-6] if len(history_rows) > 6 else history_rows
        if not older_rows:
            return

        history = [{"role": item["role"], "content": item["content"]} for item in older_rows]
        updated = self.summarizer.summarize(history, previous_summary=session.running_summary)
        if updated and updated != session.running_summary:
            session.running_summary = updated
            await self.session_store.update_summary(session.session_id, updated)

    async def _send_recoverable_error(self, websocket: Any, message: str | None = None) -> None:
        """Emit a standard recoverable error payload if the socket is still open."""
        try:
            await websocket.send_json(build_recoverable_error_payload(message))
        except Exception:  # noqa: BLE001
            return

    @staticmethod
    def _domain_refusal_text() -> str:
        """Return the fixed refusal message for off-domain requests."""
        return (
            "I can only help with SEC filings, public companies, market data, "
            "portfolio analysis, and related calculations. Ask about a ticker, filing, or company."
        )

    async def _log_interaction_async(self, session: ConversationSession, summary: str) -> None:
        """Persist interaction summary without blocking turn completion."""
        if not session.user_id:
            return
        await self.crm_tool.log_interaction(session.user_id, session.session_id, summary)

    async def _maybe_refresh_summary(self, session: ConversationSession) -> None:
        """Refresh and persist running summary at a fixed turn interval."""
        if not self.summarizer.should_summarize(session.turn_count):
            return

        await self._refresh_summary_from_session(session)

    async def _refresh_summary_from_session(self, session: ConversationSession, history_limit: int = 40) -> str:
        """Build and persist a fresh summary for a session using persisted history."""
        start = time.perf_counter()
        history_rows = await self.chat_store.get_history(session.session_id, limit=history_limit)
        history = [{"role": item["role"], "content": item["content"]} for item in history_rows]
        updated = self.summarizer.summarize(history, previous_summary=session.running_summary)
        if not updated:
            return session.running_summary or ""

        session.running_summary = updated
        await self.session_store.update_summary(session.session_id, updated)
        await self.latency_tracker.log(
            session_id=session.session_id,
            turn_id=session.turn_count,
            stage="conversation_summary",
            duration_ms=(time.perf_counter() - start) * 1000.0,
            metadata={"chars": len(updated)},
        )
        return updated

    async def refresh_session_summary(self, session_id: str, history_limit: int = 40) -> dict[str, Any]:
        """Force-refresh summary for one session and return updated session payload."""
        session = await self._load_or_create_session(session_id)
        summary = await self._refresh_summary_from_session(session, history_limit=history_limit)
        stored = await self.session_store.get_session(session_id)
        return {
            "session_id": session_id,
            "summary": summary,
            "session": stored,
        }

    async def handle_text_turn(
        self,
        session_id: str,
        message: str,
        websocket: Any,
        forced_turn_id: int | None = None,
        end_to_end_start: float | None = None,
        speak_response: bool = False,
    ) -> dict[str, Any]:
        """Process one text turn end-to-end and stream response outputs."""
        session = await self._load_or_create_session(session_id)
        if forced_turn_id is None:
            session.turn_count += 1
            turn_id = session.turn_count
        else:
            turn_id = forced_turn_id
            session.turn_count = max(session.turn_count, turn_id)

        turn_start = time.perf_counter()
        await self.chat_store.append_message(session_id, turn_id, "user", message)
        await self.session_store.touch_session(session_id, user_id=session.user_id, turn_count=session.turn_count)
        await self._maybe_update_title(session, message)

        if end_to_end_start is None:
            end_to_end_start = turn_start

        domain_start = time.perf_counter()
        domain_decision = self.domain_classifier.classify(message)
        await self.latency_tracker.log(
            session_id=session_id,
            turn_id=turn_id,
            stage="domain_check",
            duration_ms=(time.perf_counter() - domain_start) * 1000.0,
            metadata={
                "allowed": domain_decision.allowed,
                "reason": domain_decision.reason,
                "confidence": domain_decision.confidence,
            },
        )

        if not domain_decision.allowed:
            refusal_text = self._domain_refusal_text()
            await websocket.send_json(
                {
                    "type": "text_chunk",
                    "content": refusal_text,
                    "turn_id": turn_id,
                }
            )
            await self.latency_tracker.log(
                session_id=session_id,
                turn_id=turn_id,
                stage="tts_synthesis",
                duration_ms=0.0,
                metadata={"success": True, "skipped": True, "reason": "domain_refusal"},
            )
            end_to_end_ms = (time.perf_counter() - end_to_end_start) * 1000.0
            await self.latency_tracker.log(
                session_id=session_id,
                turn_id=turn_id,
                stage="end_to_end",
                duration_ms=end_to_end_ms,
                metadata={"domain_allowed": False},
            )
            session.history.append({"role": "user", "content": message})
            session.history.append({"role": "assistant", "content": refusal_text})
            session.history = self._truncate_history(session.history, max_turns=6)
            await self.chat_store.append_message(session_id, turn_id, "assistant", refusal_text)
            await self.session_store.touch_session(session_id, user_id=session.user_id, turn_count=session.turn_count)
            asyncio.create_task(self._log_interaction_async(session, refusal_text[:500]))
            breakdown = await self.latency_tracker.get_turn_breakdown(session_id, turn_id)
            return breakdown

        try:
            crm_task = asyncio.create_task(self._load_crm_context(session))
            retrieval_task = asyncio.create_task(self._retrieve_chunks(session_id, turn_id, message))
            tools_task = asyncio.create_task(self._run_tools(session_id, turn_id, message))
            summary_task = asyncio.create_task(self._ensure_summary_before_prompt(session))

            crm_context, chunks, tool_result = await asyncio.gather(crm_task, retrieval_task, tools_task)
            await summary_task
            rag_context = await self.retriever.format_context(chunks)
            tool_context, _ = tool_result

            prompt = await self._build_prompt(
                user_message=message,
                crm_context=crm_context,
                rag_context=rag_context,
                tool_context=tool_context,
                session_summary=session.running_summary,
                history=session.history,
            )

            assistant_text = await self.llm_engine.generate_streaming(
                prompt=prompt,
                websocket=websocket,
                session_id=session_id,
                turn_id=turn_id,
                latency_tracker=self.latency_tracker,
            )

            if speak_response:
                tts_start = time.perf_counter()
                tts_error: str | None = None
                audio_socket = AudioRecordingWebSocket(websocket)
                try:
                    await self.synthesizer.synthesize_streaming(assistant_text, audio_socket, turn_id=turn_id)
                except Exception as exc:  # noqa: BLE001
                    tts_error = str(exc)
                    await self._send_recoverable_error(websocket, f"TTS unavailable for this turn: {tts_error}")
                audio_base64 = audio_socket.combined_audio_base64()
                if audio_base64:
                    await self.chat_store.save_message_audio(
                        session_id=session_id,
                        turn_id=turn_id,
                        role="assistant",
                        audio_base64=audio_base64,
                        mime_type=audio_socket.mime_type,
                    )
                await self.latency_tracker.log(
                    session_id=session_id,
                    turn_id=turn_id,
                    stage="tts_synthesis",
                    duration_ms=(time.perf_counter() - tts_start) * 1000.0,
                    metadata={"success": tts_error is None, "error": tts_error},
                )
            else:
                await self.latency_tracker.log(
                    session_id=session_id,
                    turn_id=turn_id,
                    stage="tts_synthesis",
                    duration_ms=0.0,
                    metadata={"success": True, "skipped": True, "reason": "text_input"},
                )

            session.history.append({"role": "user", "content": message})
            session.history.append({"role": "assistant", "content": assistant_text})
            session.history = self._truncate_history(session.history, max_turns=6)
            await self.chat_store.append_message(session_id, turn_id, "assistant", assistant_text)
            await self.session_store.touch_session(session_id, user_id=session.user_id, turn_count=session.turn_count)
            await self._maybe_refresh_summary(session)

            asyncio.create_task(self._log_interaction_async(session, assistant_text[:500]))
        except Exception as exc:  # noqa: BLE001
            error_message = str(exc)
            await self._send_recoverable_error(websocket, f"Server error: {error_message}")
            await self.latency_tracker.log(
                session_id=session_id,
                turn_id=turn_id,
                stage="turn_error",
                duration_ms=(time.perf_counter() - end_to_end_start) * 1000.0,
                metadata={"error": error_message, "recoverable": True},
            )
            return {
                "session_id": session_id,
                "turn_id": turn_id,
                "error": error_message,
                "recoverable": True,
            }

        end_to_end_ms = (time.perf_counter() - end_to_end_start) * 1000.0
        await self.latency_tracker.log(
            session_id=session_id,
            turn_id=turn_id,
            stage="end_to_end",
            duration_ms=end_to_end_ms,
        )

        breakdown = await self.latency_tracker.get_turn_breakdown(session_id, turn_id)
        return breakdown

    async def handle_audio_turn(
        self,
        session_id: str,
        audio_bytes: bytes,
        websocket: Any,
        audio_format: str | None = None,
    ) -> dict[str, Any]:
        """Process one audio turn: STT -> text pipeline -> TTS output."""
        session = await self._load_or_create_session(session_id)
        session.turn_count += 1
        turn_id = session.turn_count
        turn_start = time.perf_counter()

        await self.session_store.touch_session(session_id, user_id=session.user_id, turn_count=session.turn_count)

        async with self.latency_tracker.measure(session_id, turn_id, "stt_transcription"):
            text, duration_ms = await self.transcriber.transcribe(audio_bytes, format_hint=audio_format)

        await websocket.send_json(
            {
                "type": "transcription",
                "text": text,
                "duration_ms": duration_ms,
            }
        )

        return await self.handle_text_turn(
            session_id=session_id,
            message=text,
            websocket=websocket,
            forced_turn_id=turn_id,
            end_to_end_start=turn_start,
            speak_response=True,
        )

    def get_active_sessions(self) -> list[dict[str, Any]]:
        """Return serialized active sessions for diagnostics endpoint."""
        self._cleanup_sessions()
        return [
            {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "turn_count": session.turn_count,
                "created_at": session.created_at.isoformat(),
                "last_activity": session.last_activity.isoformat(),
            }
            for session in self.sessions.values()
        ]
