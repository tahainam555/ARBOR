"""Conversation orchestration pipeline for text and voice turns."""

from __future__ import annotations

import asyncio
<<<<<<< HEAD
import logging
import re
=======
import base64
>>>>>>> ac7f852436c596021d363a069857b81fad70556e
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


logger = logging.getLogger("sec-assistant")

MAX_HISTORY_TURNS = 4

SYSTEM_PROMPT = (
    "You are an expert SEC investment research assistant. Answer questions using the provided "
    "SEC filing excerpts. Be precise with numbers. Cite your sources (e.g., 'According to Apple's "
    "2023 10-K...'). If information is not in the provided context, say so clearly. Keep replies "
    "brief, ideally 2-4 short sentences unless the user asks for detail."
)


@dataclass
class ConversationSession:
    """In-memory state for one active user conversation."""

    session_id: str
    user_id: str | None = None
    running_summary: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    entity_memory: dict[str, Any] = field(default_factory=dict)
    turn_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EntityMemoryExtractor:
    """Fast rule-based extraction of durable user facts."""

    _watchlist_stopwords = {"AND", "OR", "THE", "A", "AN", "BUT", "FOR", "TO", "OF"}

    _name_patterns = (
        re.compile(r"\b(?:my name is|call me|i'm|i am)\s+([^.,!?;]+)", re.IGNORECASE),
    )
    _risk_patterns = (
        re.compile(r"\b(?:i am|i'm|i prefer|my risk tolerance is)\s+(?:a\s+|an\s+)?(conservative|moderate|aggressive)\b", re.IGNORECASE),
        re.compile(r"\bprefer\s+(low|medium|high)\s+risk\b", re.IGNORECASE),
    )
    _interest_patterns = (
        re.compile(r"\b(?:i'?m interested in|i am interested in|interested in)\s+([^.,!?;]+)", re.IGNORECASE),
        re.compile(r"\b(?:i focus on|focus on)\s+([^.,!?;]+)", re.IGNORECASE),
    )
    _holding_patterns = (
        re.compile(r"\b(?:i own|i hold)\s+(\d+(?:\.\d+)?)\s+shares?\s+of\s+\$?([A-Z]{1,5})\b", re.IGNORECASE),
        re.compile(r"\b(?:i bought|bought)\s+\$?([A-Z]{1,5})\s+at\s+\$?(\d+(?:\.\d+)?)\b", re.IGNORECASE),
        re.compile(r"\b(?:i bought|bought)\s+(\d+(?:\.\d+)?)\s+shares?\s+of\s+\$?([A-Z]{1,5})\b", re.IGNORECASE),
    )
    _watchlist_patterns = (
        re.compile(r"\b(?:i'?m watching|i am watching|watching|keep an eye on)\s+([^.,!?;]+)", re.IGNORECASE),
    )
    _goal_patterns = (
        re.compile(r"\bretire in\s+([^.,!?;]+)", re.IGNORECASE),
        re.compile(r"\bsaving for\s+([^.,!?;]+)", re.IGNORECASE),
    )

    @staticmethod
    def _append_unique(target: list[Any], values: list[Any]) -> None:
        for value in values:
            if value not in target:
                target.append(value)

    @staticmethod
    def _clean_name(candidate: str) -> str | None:
        cleaned = re.sub(r"\s+", " ", candidate).strip(" \"'\n\t,.;:!?")
        cleaned = re.split(r"\b(?:and|but|because|so|with|for|to|if|who|what|when|where|why)\b", cleaned, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        cleaned = re.sub(r"^(?:a|an|the)\s+", "", cleaned, flags=re.IGNORECASE)
        if not cleaned:
            return None
        parts = cleaned.split()
        if len(parts) > 4:
            return None
        first_word = parts[0].lower()
        if first_word in {"watching", "watch", "interested", "saving", "retire", "prefer"}:
            return None
        if any(token.lower() in {"investor", "investing", "aggressive", "moderate", "conservative", "risk"} for token in parts):
            return None
        if not all(re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", token) for token in parts):
            return None
        return " ".join(part.capitalize() for part in parts)

    @staticmethod
    def _split_terms(text: str) -> list[str]:
        parts = re.split(r"\s*(?:,|/| and | or |&)\s*", text, flags=re.IGNORECASE)
        cleaned: list[str] = []
        for part in parts:
            item = re.sub(r"\s+", " ", part).strip(" \"'\n\t,.;:!?")
            if not item:
                continue
            item = re.sub(r"\bstocks?\b|\bshares?\b|\binvestments?\b|\binvestors?\b", "", item, flags=re.IGNORECASE)
            item = re.sub(r"\s+", " ", item).strip(" \"'\n\t,.;:!?")
            if item:
                cleaned.append(item.lower())
        return cleaned

    @staticmethod
    def _clone_memory(existing_memory: dict[str, Any]) -> dict[str, Any]:
        clone: dict[str, Any] = {}
        for key, value in existing_memory.items():
            if isinstance(value, list):
                clone[key] = list(value)
            elif isinstance(value, dict):
                clone[key] = dict(value)
            else:
                clone[key] = value
        return clone

    def extract(self, user_message: str, assistant_response: str, existing_memory: dict[str, Any]) -> dict[str, Any]:
        """Merge extracted facts from both messages into the session memory."""
        memory = self._clone_memory(existing_memory)
        texts = (user_message, assistant_response)

        names: list[str] = []
        risk_profile: str | None = None
        interests: list[str] = list(memory.get("interests", [])) if isinstance(memory.get("interests"), list) else []
        holdings: list[dict[str, Any]] = list(memory.get("mentioned_holdings", [])) if isinstance(memory.get("mentioned_holdings"), list) else []
        watchlist: list[str] = list(memory.get("watchlist", [])) if isinstance(memory.get("watchlist"), list) else []
        goals: list[str] = list(memory.get("goals", [])) if isinstance(memory.get("goals"), list) else []

        for text in texts:
            for pattern in self._name_patterns:
                for match in pattern.findall(text):
                    candidate = self._clean_name(match)
                    if candidate:
                        names.append(candidate)

            for pattern in self._risk_patterns:
                for match in pattern.findall(text):
                    if isinstance(match, tuple):
                        values = [item.lower() for item in match if item]
                        if values:
                            risk_profile = values[-1]
                    elif match:
                        risk_profile = str(match).lower()

            for pattern in self._interest_patterns:
                for raw in pattern.findall(text):
                    items = self._split_terms(str(raw))
                    self._append_unique(interests, items)

            for pattern in self._holding_patterns:
                for match in pattern.findall(text):
                    if len(match) != 2:
                        continue
                    first, second = match
                    if pattern == self._holding_patterns[1]:
                        ticker = str(first).upper()
                        context = f"Bought {ticker} at ${second}"
                    else:
                        ticker = str(second).upper()
                        context = f"Owns {first} shares of {ticker}"
                    holdings.append({"ticker": ticker, "context": context})

            for pattern in self._watchlist_patterns:
                for raw in pattern.findall(text):
                    items = [
                        item.upper()
                        for item in re.findall(r"\b[A-Z]{2,5}\b", str(raw), flags=re.IGNORECASE)
                        if item.upper() not in self._watchlist_stopwords
                    ]
                    self._append_unique(watchlist, items)

            for pattern in self._goal_patterns:
                for raw in pattern.findall(text):
                    goal = re.sub(r"\s+", " ", str(raw)).strip(" \"'\n\t,.;:!?")
                    if goal:
                        goals.append(goal)

        if names:
            memory["user_name"] = names[0]
        if risk_profile:
            memory["risk_profile"] = risk_profile
        if interests:
            memory["interests"] = interests
        if holdings:
            memory["mentioned_holdings"] = holdings
        if watchlist:
            memory["watchlist"] = [item.upper() for item in watchlist]
        if goals:
            memory["goals"] = goals

        return memory


class SessionManager:
    """Thread-safe session store with expiration and CRM-backed bootstrap."""

    def __init__(self, crm_tool: CRMTool, max_sessions: int, session_timeout_minutes: int) -> None:
        self.crm_tool = crm_tool
        self.max_sessions = max_sessions
        self.session_timeout = timedelta(minutes=session_timeout_minutes)
        self._sessions: dict[str, ConversationSession] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _crm_to_entity_memory(crm_data: dict[str, Any]) -> dict[str, Any]:
        entity_memory: dict[str, Any] = {}
        name = crm_data.get("name")
        if name:
            entity_memory["user_name"] = name

        risk_profile = crm_data.get("risk_profile")
        if risk_profile:
            entity_memory["risk_profile"] = risk_profile

        investment_goals = crm_data.get("investment_goals") or []
        if investment_goals:
            entity_memory["goals"] = list(investment_goals)

        watchlist = crm_data.get("watchlist") or []
        if watchlist:
            entity_memory["watchlist"] = [str(item).upper() for item in watchlist]

        portfolio = crm_data.get("portfolio") or {}
        if isinstance(portfolio, dict) and portfolio:
            entity_memory["mentioned_holdings"] = [
                {"ticker": str(ticker).upper(), "context": str(payload)}
                for ticker, payload in portfolio.items()
            ]

        return entity_memory

    def _cleanup_locked(self) -> None:
        now = self._utcnow()
        expired = [sid for sid, session in self._sessions.items() if now - session.last_active > self.session_timeout]
        for sid in expired:
            self._sessions.pop(sid, None)

        if len(self._sessions) <= self.max_sessions:
            return

        overflow = len(self._sessions) - self.max_sessions
        oldest = sorted(self._sessions.values(), key=lambda session: session.last_active)
        for session in oldest[:overflow]:
            self._sessions.pop(session.session_id, None)

    async def get_or_create(self, session_id: str, user_id: str | None = None) -> ConversationSession:
        async with self._lock:
            self._cleanup_locked()
            session = self._sessions.get(session_id)
            if session is None:
                entity_memory: dict[str, Any] = {}
                if user_id:
                    crm_data = await self.crm_tool.get_user(user_id)
                    if crm_data:
                        entity_memory = self._crm_to_entity_memory(crm_data)
                        logger.info("Bootstrapped session from CRM: session=%s user_id=%s crm_loaded=True", session_id, user_id)
                    else:
                        logger.info("Bootstrapped session with no CRM entry: session=%s user_id=%s", session_id, user_id)

                session = ConversationSession(
                    session_id=session_id,
                    user_id=user_id,
                    history=[],
                    entity_memory=entity_memory,
                    turn_count=0,
                    created_at=self._utcnow(),
                    last_active=self._utcnow(),
                )
                self._sessions[session_id] = session
            else:
                if user_id and session.user_id is None:
                    session.user_id = user_id
                session.last_active = self._utcnow()
                logger.debug("Session touched: session=%s user_id=%s last_active=%s", session_id, session.user_id, session.last_active.isoformat())

            return session

    async def cleanup_expired(self) -> None:
        async with self._lock:
            self._cleanup_locked()

    async def list_sessions(self) -> list[ConversationSession]:
        async with self._lock:
            self._cleanup_locked()
            return list(self._sessions.values())


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
<<<<<<< HEAD
        self.session_manager = SessionManager(
            crm_tool=crm_tool,
            max_sessions=self.settings.max_sessions,
            session_timeout_minutes=self.settings.session_timeout_minutes,
        )
        self.entity_extractor = EntityMemoryExtractor()
=======
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
>>>>>>> ac7f852436c596021d363a069857b81fad70556e

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
    def _truncate_history(history: list[dict[str, str]], max_turns: int = MAX_HISTORY_TURNS) -> list[dict[str, str]]:
        return history[-(max_turns * 2):]

    @staticmethod
    def _truncate_text_by_token_estimate(text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""

        words = text.split()
        max_words = max(1, int(max_tokens / 1.3))
        if len(words) <= max_words:
            return text
        return " ".join(words[-max_words:])

    @staticmethod
    def _build_sources_footer(chunks: list[RetrievedChunk], max_sources: int = 3) -> str:
        """Create a compact, deterministic citation footer from retrieved chunks."""
        if not chunks:
            return ""

        unique_sources: list[str] = []
        seen: set[str] = set()
        for chunk in chunks:
            source = f"{chunk.ticker} {chunk.filing_type} {chunk.year} ({chunk.source})"
            if source in seen:
                continue
            seen.add(source)
            unique_sources.append(source)
            if len(unique_sources) >= max_sources:
                break

        if not unique_sources:
            return ""
        return "\n\nSources: " + "; ".join(unique_sources)

    async def _load_crm_context(self, session: ConversationSession) -> str:
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

    def build_system_prompt(self, session: ConversationSession, crm_context: str) -> str:
        facts: list[str] = []
        memory = session.entity_memory
        if memory.get("user_name"):
            facts.append(f"User's name: {memory['user_name']}")
        if memory.get("risk_profile"):
            facts.append(f"Risk profile: {memory['risk_profile']}")
        if memory.get("interests"):
            facts.append(f"Investment interests: {', '.join(memory['interests'])}")
        if memory.get("watchlist"):
            facts.append(f"Watchlist: {', '.join(memory['watchlist'])}")
        if memory.get("goals"):
            facts.append(f"Goals: {'; '.join(memory['goals'])}")

        sections = [SYSTEM_PROMPT]
        if facts:
            sections.append("KNOWN USER FACTS (always use these):\n" + "\n".join(f"- {fact}" for fact in facts))
        if crm_context and crm_context != "No user profile loaded.":
            sections.append("CRM PROFILE:\n" + crm_context)
        return "\n\n".join(sections)

    @staticmethod
    def _format_history(history: list[dict[str, str]]) -> str:
        lines: list[str] = []
        for item in history:
            role = item.get("role", "user")
            content = item.get("content", "")
            lines.append(
                f"<|start_header_id|>{role}<|end_header_id|>\n"
                f"{content}<|eot_id|>"
            )
        return "\n".join(lines)

    async def _retrieve_chunks(
        self,
        session_id: str,
        turn_id: int,
        message: str,
    ) -> list[RetrievedChunk]:
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
        websocket: Any | None = None,
    ) -> tuple[str, dict[str, Any]]:
        async with self.latency_tracker.measure(session_id, turn_id, "tool_detection"):
            tool_result = await self.tool_orchestrator.detect_and_execute(message=message, session_id=session_id)

        if websocket is not None:
            for detection in getattr(tool_result, "detections", []):
                await websocket.send_json(
                    {
                        "type": "tool_call",
                        "tool_name": detection.get("tool"),
                        "args": detection.get("params", {}),
                        "turn_id": turn_id,
                    }
                )

        for tool_name, result in tool_result.results.items():
            await self.latency_tracker.log(
                session_id=session_id,
                turn_id=turn_id,
                stage=f"tool_execution_{tool_name}",
                duration_ms=float(result.get("duration_ms", 0.0)),
                metadata={"success": result.get("success", False)},
            )

        return tool_result.formatted_context, tool_result.results

    async def _build_prompt(
        self,
        session: ConversationSession,
        user_message: str,
        crm_context: str,
        rag_context: str,
        tool_context: str,
<<<<<<< HEAD
    ) -> str:
        system_prompt = self.build_system_prompt(session, crm_context)
        history_text = self._format_history(self._truncate_history(session.history))
        history_text = self._truncate_text_by_token_estimate(history_text, max_tokens=220)
        rag_context = self._truncate_text_by_token_estimate(rag_context, max_tokens=800)
        tool_context = self._truncate_text_by_token_estimate(tool_context, max_tokens=200)
=======
        session_summary: str | None,
        history: list[dict[str, str]],
    ) -> str:
        """Build strict llama-3.2 instruct prompt format."""
        history_text = self._format_history(self._truncate_history(history, max_turns=4))
        history_text = self._truncate_text_by_token_estimate(history_text, max_tokens=350)
        rag_context = self._truncate_text_by_token_estimate(rag_context, max_tokens=2000)
        tool_context = self._truncate_text_by_token_estimate(tool_context, max_tokens=500)
        summary_context = self._truncate_text_by_token_estimate(session_summary or "No prior session summary.", max_tokens=450)
>>>>>>> ac7f852436c596021d363a069857b81fad70556e

        logger.debug("Prompt history turns: %s", len(session.history))
        logger.debug("Entity memory: %s", session.entity_memory)

        return (
            "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n"
            f"{system_prompt}\n\n"
            "RETRIEVED CONTEXT:\n"
            f"{rag_context}\n\n"
            "TOOL RESULTS:\n"
<<<<<<< HEAD
            f"{tool_context}\n"
=======
            f"{tool_context}\n\n"
            "SESSION SUMMARY:\n"
            f"{summary_context}\n\n"
            "RECENT HISTORY:\n"
            f"{history_text}\n"
>>>>>>> ac7f852436c596021d363a069857b81fad70556e
            "<|eot_id|>\n"
            f"{history_text}\n"
            "<|start_header_id|>user<|end_header_id|>\n"
            f"{user_message}\n"
            "<|eot_id|>\n"
            "<|start_header_id|>assistant<|end_header_id|>\n"
        )

    async def _sync_entity_memory_to_crm(self, session: ConversationSession) -> None:
        if not session.user_id:
            logger.debug("_sync_entity_memory_to_crm skipped: no user_id (session=%s)", session.session_id)
            return

        memory = session.entity_memory
        logger.info("Syncing entity memory to CRM: session=%s user_id=%s keys=%s", session.session_id, session.user_id, list(memory.keys()))

        try:
            if memory.get("user_name"):
                existing = await self.crm_tool.get_user(session.user_id)
                if existing is None:
                    created = await self.crm_tool.create_user(session.user_id, str(memory["user_name"]))
                    logger.info("CRM create_user result: session=%s user_id=%s created=%s", session.session_id, session.user_id, bool(created))
                elif existing.get("name") != memory["user_name"]:
                    ok = await self.crm_tool.update_field(session.user_id, "name", memory["user_name"])
                    logger.info("CRM update_field(name) result: session=%s user_id=%s ok=%s", session.session_id, session.user_id, ok)

            if memory.get("risk_profile"):
                ok = await self.crm_tool.update_field(session.user_id, "risk_profile", memory["risk_profile"])
                logger.info("CRM update_field(risk_profile): session=%s user_id=%s ok=%s", session.session_id, session.user_id, ok)

            if memory.get("goals"):
                ok = await self.crm_tool.update_field(session.user_id, "investment_goals", memory["goals"])
                logger.info("CRM update_field(investment_goals): session=%s user_id=%s ok=%s", session.session_id, session.user_id, ok)

            if memory.get("watchlist"):
                for ticker in memory["watchlist"]:
                    ok = await self.crm_tool.add_to_watchlist(session.user_id, ticker)
                    logger.info("CRM add_to_watchlist: session=%s user_id=%s ticker=%s ok=%s", session.session_id, session.user_id, ticker, ok)
        except Exception:
            logger.exception("Error syncing entity memory to CRM: session=%s user_id=%s", session.session_id, session.user_id)

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
        if not session.user_id:
            logger.debug("_log_interaction_async skipped: no user_id (session=%s)", session.session_id)
            return
        try:
            ok = await self.crm_tool.log_interaction(session.user_id, session.session_id, summary)
            logger.info("CRM log_interaction: session=%s user_id=%s ok=%s", session.session_id, session.user_id, ok)
        except Exception:
            logger.exception("Failed to log interaction: session=%s user_id=%s", session.session_id, session.user_id)

    async def _finalize_turn(
        self,
        session: ConversationSession,
        session_id: str,
        turn_id: int,
        user_message: str,
        assistant_text: str,
        end_to_end_start: float,
    ) -> dict[str, Any]:
        session.history.append({"role": "user", "content": user_message})
        session.history.append({"role": "assistant", "content": assistant_text})
        session.history = self._truncate_history(session.history)
        session.entity_memory = self.entity_extractor.extract(user_message, assistant_text, session.entity_memory)
        session.turn_count = max(session.turn_count, turn_id)
        session.last_active = datetime.now(timezone.utc)

        asyncio.create_task(self._log_interaction_async(session, assistant_text[:500]))
        asyncio.create_task(self._sync_entity_memory_to_crm(session))

        await self.latency_tracker.log(
            session_id=session_id,
            turn_id=turn_id,
            stage="end_to_end",
            duration_ms=(time.perf_counter() - end_to_end_start) * 1000.0,
        )
        return await self.latency_tracker.get_turn_breakdown(session_id, turn_id)

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
        user_id: str | None = None,
        forced_turn_id: int | None = None,
        end_to_end_start: float | None = None,
        speak_response: bool = False,
    ) -> dict[str, Any]:
<<<<<<< HEAD
        session = await self.session_manager.get_or_create(session_id, user_id=user_id)
=======
        """Process one text turn end-to-end and stream response outputs."""
        session = await self._load_or_create_session(session_id)
>>>>>>> ac7f852436c596021d363a069857b81fad70556e
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

<<<<<<< HEAD
        crm_task = asyncio.create_task(self._load_crm_context(session))
        retrieval_task = asyncio.create_task(self._retrieve_chunks(session_id, turn_id, message))
        tools_task = asyncio.create_task(self._run_tools(session_id, turn_id, message, websocket=websocket))

        crm_context, chunks, tool_result = await asyncio.gather(crm_task, retrieval_task, tools_task)
        rag_context = await self.retriever.format_context(chunks)
        tool_context, _ = tool_result

        prompt = await self._build_prompt(
            session=session,
            user_message=message,
            crm_context=crm_context,
            rag_context=rag_context,
            tool_context=tool_context,
        )

        assistant_text = await self.llm_engine.generate_streaming(
            prompt=prompt,
            websocket=websocket,
=======
        domain_start = time.perf_counter()
        domain_decision = self.domain_classifier.classify(message)
        await self.latency_tracker.log(
>>>>>>> ac7f852436c596021d363a069857b81fad70556e
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
        assistant_text = (assistant_text + self._build_sources_footer(chunks)).strip()

<<<<<<< HEAD
        if speak_response:
            await self.synthesizer.synthesize_streaming(assistant_text, websocket, turn_id=turn_id)
        else:
=======
        if not domain_decision.allowed:
            refusal_text = self._domain_refusal_text()
            await websocket.send_json(
                {
                    "type": "text_chunk",
                    "content": refusal_text,
                    "turn_id": turn_id,
                }
            )
>>>>>>> ac7f852436c596021d363a069857b81fad70556e
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

        return await self._finalize_turn(
            session=session,
            session_id=session_id,
            turn_id=turn_id,
            user_message=message,
            assistant_text=assistant_text,
            end_to_end_start=end_to_end_start,
        )

<<<<<<< HEAD
    async def handle_voice_turn(
        self,
        session_id: str,
        audio_bytes: bytes,
        websocket: Any,
        user_id: str | None = None,
        audio_format: str | None = None,
    ) -> dict[str, Any]:
        session = await self.session_manager.get_or_create(session_id, user_id=user_id)
        session.turn_count += 1
        turn_id = session.turn_count
        end_to_end_start = time.perf_counter()

        async with self.latency_tracker.measure(session_id, turn_id, "stt_transcription"):
            user_text, duration_ms = await self.transcriber.transcribe(audio_bytes, format_hint=audio_format)

        await websocket.send_json(
            {
                "type": "transcription",
                "text": user_text,
                "duration_ms": duration_ms,
            }
        )

        crm_task = asyncio.create_task(self._load_crm_context(session))
        retrieval_task = asyncio.create_task(self._retrieve_chunks(session_id, turn_id, user_text))
        tools_task = asyncio.create_task(self._run_tools(session_id, turn_id, user_text, websocket=websocket))

        crm_context, chunks, tool_result = await asyncio.gather(crm_task, retrieval_task, tools_task)
        rag_context = await self.retriever.format_context(chunks)
        tool_context, _ = tool_result

        prompt = await self._build_prompt(
            session=session,
            user_message=user_text,
            crm_context=crm_context,
            rag_context=rag_context,
            tool_context=tool_context,
        )

        sentence_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=5)
        llm_task = asyncio.create_task(
            self.llm_engine.generate_sentence_streaming(
                prompt=prompt,
                sentence_queue=sentence_queue,
                websocket=websocket,
                session_id=session_id,
                turn_id=turn_id,
                latency_tracker=self.latency_tracker,
            )
        )
        tts_task = asyncio.create_task(
            self.synthesizer.consume_and_stream(
                sentence_queue=sentence_queue,
                websocket=websocket,
                turn_id=turn_id,
                latency_tracker=self.latency_tracker,
                session_id=session_id,
            )
        )

        try:
            assistant_text, _ = await asyncio.gather(llm_task, tts_task)
        except Exception as exc:  # noqa: BLE001
            llm_task.cancel()
            tts_task.cancel()
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Voice pipeline error: {exc}",
                    "recoverable": True,
                }
            )
            return await self.latency_tracker.get_turn_breakdown(session_id, turn_id)

        assert assistant_text != user_text, (
            f"BUG: TTS is about to synthesize user input '{user_text[:50]}' instead of assistant response"
        )
        assert len(assistant_text) > 0, "BUG: Empty assistant response passed to TTS"

        assistant_text = (assistant_text + self._build_sources_footer(chunks)).strip()

        return await self._finalize_turn(
            session=session,
            session_id=session_id,
            turn_id=turn_id,
            user_message=user_text,
            assistant_text=assistant_text,
            end_to_end_start=end_to_end_start,
        )
=======
        breakdown = await self.latency_tracker.get_turn_breakdown(session_id, turn_id)
        return breakdown
>>>>>>> ac7f852436c596021d363a069857b81fad70556e

    async def handle_audio_turn(
        self,
        session_id: str,
        audio_bytes: bytes,
        websocket: Any,
        user_id: str | None = None,
        audio_format: str | None = None,
    ) -> dict[str, Any]:
<<<<<<< HEAD
        return await self.handle_voice_turn(
=======
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
>>>>>>> ac7f852436c596021d363a069857b81fad70556e
            session_id=session_id,
            audio_bytes=audio_bytes,
            websocket=websocket,
            user_id=user_id,
            audio_format=audio_format,
        )

    async def get_active_sessions(self) -> list[dict[str, Any]]:
        sessions = await self.session_manager.list_sessions()
        return [
            {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "turn_count": session.turn_count,
                "created_at": session.created_at.isoformat(),
                "last_active": session.last_active.isoformat(),
            }
            for session in sessions
        ]
