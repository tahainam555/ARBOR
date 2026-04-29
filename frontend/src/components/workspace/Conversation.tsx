import {
  ArrowUp,
  Paperclip,
  Sparkles,
  ChevronDown,
  AudioLines,
  Sun,
  Moon,
  Mic,
  Volume2,
  Square,
  XCircle,
} from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "@/components/theme/ThemeProvider";
import { backendBaseUrl, getCurrentSessionId, websocketUrl } from "@/lib/backend";

interface ConversationProps {
  intelligenceOpen: boolean;
  onToggleIntelligence: () => void;
}

type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  streaming?: boolean;
  audio?: string;
  mimeType?: string;
};

type PendingAudio = {
  audio: string;
  format: string;
};

type AudioResponseChunk = {
  bytes: Uint8Array;
  mimeType: string;
};

const SESSION_EVENT = "arbor-session-changed";

function makeId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function Conversation({ intelligenceOpen, onToggleIntelligence }: ConversationProps) {
  const { theme, toggle: toggleTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [sessionId, setSessionId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(false);
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [lastLatency, setLastLatency] = useState<Record<string, number> | null>(null);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const pendingMessageRef = useRef<string | null>(null);
  const pendingAudioRef = useRef<PendingAudio | null>(null);
  const socketGenerationRef = useRef(0);
  const mountedRef = useRef(false);
  const sessionRef = useRef<string>("");
  const streamingIdRef = useRef<string | null>(null);
  const streamingBufferRef = useRef("");
  const streamingFrameRef = useRef<number | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordingChunksRef = useRef<BlobPart[]>([]);
  const cancelRecordingRef = useRef(false);
  const audioResponseChunksRef = useRef<AudioResponseChunk[]>([]);
  const audioResponseMimeTypeRef = useRef("audio/mpeg");
  const playedAudioChunkCountRef = useRef(0);
  const currentAudioSentenceRef = useRef<number | null>(null);
  const shouldAutoScrollRef = useRef(true);
  const connectWebSocketRef = useRef<(targetSessionId: string) => void>(() => {});

  useEffect(() => {
    mountedRef.current = true;
    setMounted(true);
    setSessionId(getCurrentSessionId());
    return () => {
      mountedRef.current = false;
      if (streamingFrameRef.current !== null) {
        window.cancelAnimationFrame(streamingFrameRef.current);
      }
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      }
    };
  }, []);

  // ============================================================================
  // Websocket lifecycle and utilities
  // ============================================================================

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const closeSocketQuietly = useCallback((socket: WebSocket | null) => {
    if (!socket) return;
    socket.onopen = null;
    socket.onclose = null;
    socket.onerror = null;
    socket.onmessage = null;
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CLOSING) {
      try {
        socket.close();
      } catch {
        // noop
      }
    }
  }, []);

  const flushStreamingBuffer = useCallback(() => {
    streamingFrameRef.current = null;
    const chunk = streamingBufferRef.current;
    const activeId = streamingIdRef.current;
    if (!chunk || !activeId) return;

    streamingBufferRef.current = "";
    setMessages((prev) =>
      prev.map((message) =>
        message.id === activeId
          ? { ...message, content: `${message.content}${chunk}`, streaming: true }
          : message,
      ),
    );
  }, []);

  const queueAssistantChunk = useCallback(
    (chunk: string) => {
      if (!chunk) return;

      let activeId = streamingIdRef.current;
      if (!activeId) {
        activeId = makeId("assistant");
        streamingIdRef.current = activeId;
        setStreamingId(activeId);
        setMessages((prev) => [
          ...prev,
          { id: activeId, role: "assistant", content: "", streaming: true },
        ]);
      }

      streamingBufferRef.current += chunk;
      if (streamingFrameRef.current === null) {
        streamingFrameRef.current = window.requestAnimationFrame(flushStreamingBuffer);
      }
    },
    [flushStreamingBuffer],
  );

  const finishStreamingMessage = useCallback(() => {
    if (streamingFrameRef.current !== null) {
      window.cancelAnimationFrame(streamingFrameRef.current);
      flushStreamingBuffer();
    }

    const activeId = streamingIdRef.current;
    if (activeId) {
      setMessages((prev) =>
        prev.map((message) =>
          message.id === activeId ? { ...message, streaming: false } : message,
        ),
      );
    }

    streamingIdRef.current = null;
    streamingBufferRef.current = "";
    setStreamingId(null);
  }, [flushStreamingBuffer]);

  const sendPendingAudio = useCallback((socket: WebSocket) => {
    const pending = pendingAudioRef.current;
    if (!pending) return;

    socket.send(
      JSON.stringify({
        type: "audio_input",
        audio: pending.audio,
        format: pending.format,
      }),
    );
    pendingAudioRef.current = null;
  }, []);

  const playAudioBlob = useCallback((audioBase64: string, mimeType = "audio/mpeg") => {
    if (!audioBase64) return;

    try {
      const binary = window.atob(audioBase64);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
      }
      const blob = new Blob([bytes], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      audio.onerror = () => URL.revokeObjectURL(url);
      void audio.play().catch(() => URL.revokeObjectURL(url));
    } catch {
      // Replay is optional; failed audio should never block chat.
    }
  }, []);

  const playCollectedAudio = useCallback(() => {
    const chunks = audioResponseChunksRef.current;
    if (chunks.length === 0) return "";

    const mimeType = audioResponseMimeTypeRef.current;
    const activeId = streamingIdRef.current;
    const unplayedChunks = chunks.slice(playedAudioChunkCountRef.current);
    playedAudioChunkCountRef.current = chunks.length;

    // Play unplayed chunks immediately
    if (unplayedChunks.length > 0) {
      const playbackBlob = new Blob(
        unplayedChunks.map((chunk) => chunk.bytes),
        { type: mimeType },
      );
      const playbackUrl = URL.createObjectURL(playbackBlob);
      const playback = new Audio(playbackUrl);
      playback.onended = () => URL.revokeObjectURL(playbackUrl);
      playback.onerror = () => URL.revokeObjectURL(playbackUrl);
      void playback.play().catch(() => URL.revokeObjectURL(playbackUrl));
    }

    // Store full audio for replay button (don't play it again)
    const blob = new Blob(
      chunks.map((chunk) => chunk.bytes),
      { type: mimeType },
    );

    const reader = new FileReader();
    reader.onloadend = () => {
      const dataUrl = typeof reader.result === "string" ? reader.result : "";
      const base64 = dataUrl.split(",")[1] ?? "";
      if (!base64) return;

      if (activeId) {
        setMessages((prev) =>
          prev.map((message) =>
            message.id === activeId ? { ...message, audio: base64, mimeType } : message,
          ),
        );
      }
    };
    reader.readAsDataURL(blob);
    return "";
  }, []);

  const scheduleReconnect = useCallback(
    (targetSessionId: string) => {
      clearReconnectTimer();
      setIsReconnecting(true);
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        connectWebSocketRef.current(targetSessionId);
      }, 1200);
    },
    [clearReconnectTimer],
  );

  const safelySetConnected = useCallback((value: boolean, generation: number) => {
    if (socketGenerationRef.current !== generation || !mountedRef.current) {
      return;
    }
    setConnected(value);
  }, []);

  const connectWebSocket = useCallback(
    (targetSessionId: string) => {
      if (!targetSessionId) return;

      clearReconnectTimer();
      setIsReconnecting(false);

      // Close old socket before opening new one
      closeSocketQuietly(wsRef.current);
      wsRef.current = null;

      const generation = ++socketGenerationRef.current;
      const ws = new WebSocket(websocketUrl(targetSessionId));
      wsRef.current = ws;

      ws.onopen = () => {
        safelySetConnected(true, generation);
        setIsReconnecting(false);
        if (pendingMessageRef.current) {
          const pending = pendingMessageRef.current;
          pendingMessageRef.current = null;
          ws.send(JSON.stringify({ type: "text_input", message: pending }));
        }
        sendPendingAudio(ws);
      };

      ws.onclose = () => {
        safelySetConnected(false, generation);
        // Only trigger reconnect if socket is still current generation
        if (
          socketGenerationRef.current === generation &&
          mountedRef.current &&
          wsRef.current === ws
        ) {
          scheduleReconnect(targetSessionId);
        }
      };
      ws.onerror = () => {
        safelySetConnected(false, generation);
      };

      ws.onmessage = (event) => {
        // Ignore messages from old sockets
        if (wsRef.current !== ws) return;

        try {
          const msg = JSON.parse(event.data) as {
            type?: string;
            content?: string;
            message?: string;
            text?: string;
            audio?: string;
            mime_type?: string;
            sentence_index?: number;
            latency_breakdown?: Record<string, number>;
          };

          if (msg.type === "text_chunk") {
            queueAssistantChunk(msg.content ?? "");
            return;
          }

          if (msg.type === "transcription") {
            const transcript = (msg.text ?? "").trim();
            if (transcript) {
              setMessages((prev) => [
                ...prev,
                { id: makeId("user"), role: "user", content: transcript },
              ]);
            }
            return;
          }

          if (msg.type === "audio_chunk" && msg.audio) {
            try {
              const sentenceIndex = Number(msg.sentence_index ?? 0);
              if (
                currentAudioSentenceRef.current !== null &&
                sentenceIndex !== currentAudioSentenceRef.current
              ) {
                playCollectedAudio();
              }
              currentAudioSentenceRef.current = sentenceIndex;

              const binary = window.atob(msg.audio);
              const bytes = new Uint8Array(binary.length);
              for (let index = 0; index < binary.length; index += 1) {
                bytes[index] = binary.charCodeAt(index);
              }
              audioResponseChunksRef.current.push({
                bytes,
                mimeType: msg.mime_type ?? "audio/mpeg",
              });
              audioResponseMimeTypeRef.current = msg.mime_type ?? "audio/mpeg";
            } catch {
              // Audio playback is best-effort; text remains the source of truth.
            }
            return;
          }

          if (msg.type === "turn_complete") {
            setIsSending(false);
            setIsTranscribing(false);
            playCollectedAudio();
            finishStreamingMessage();
            setIsReconnecting(false);
            if (msg.latency_breakdown) {
              setLastLatency(msg.latency_breakdown);
            }
            window.dispatchEvent(new Event("arbor-refresh-sessions"));
            return;
          }

          if (msg.type === "error") {
            setIsSending(false);
            setIsTranscribing(false);
            finishStreamingMessage();
            setIsReconnecting(false);
            setMessages((prev) => [
              ...prev,
              {
                id: makeId("system"),
                role: "system",
                content: `Error: ${msg.message ?? "Unknown error"}`,
              },
            ]);
          }
        } catch {
          setMessages((prev) => [
            ...prev,
            {
              id: makeId("system"),
              role: "system",
              content: "Received unexpected server payload.",
            },
          ]);
        }
      };
    },
    [
      clearReconnectTimer,
      closeSocketQuietly,
      finishStreamingMessage,
      playCollectedAudio,
      queueAssistantChunk,
      safelySetConnected,
      scheduleReconnect,
      sendPendingAudio,
    ],
  );

  useEffect(() => {
    connectWebSocketRef.current = connectWebSocket;
  }, [connectWebSocket]);

  const loadHistory = useCallback(async (targetSessionId: string) => {
    try {
      const res = await fetch(`${backendBaseUrl()}/api/sessions/${targetSessionId}/history`);
      if (!res.ok) throw new Error(`Failed to load history (${res.status})`);
      const data = (await res.json()) as {
        messages?: Array<{
          role?: string;
          message?: string;
          text?: string;
          content?: string;
          audio?: string;
          mime_type?: string;
        }>;
      };
      const normalized = (data.messages ?? []).map((m, idx) => ({
        id: makeId(`history-${idx}`),
        role: (m.role === "user" || m.role === "assistant"
          ? m.role
          : "system") as ChatMessage["role"],
        content: m.message ?? m.text ?? m.content ?? "",
        audio: m.audio,
        mimeType: m.mime_type,
      }));
      setMessages(normalized);
    } catch {
      setMessages([
        { id: makeId("system"), role: "system", content: "Unable to load session history." },
      ]);
    }
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    sessionRef.current = sessionId;
    setMessages([]);
    finishStreamingMessage();
    setIsSending(false);
    setIsTranscribing(false);
    setVoiceError(null);
    pendingMessageRef.current = null;
    pendingAudioRef.current = null;
    audioResponseChunksRef.current = [];
    audioResponseMimeTypeRef.current = "audio/mpeg";
    playedAudioChunkCountRef.current = 0;
    currentAudioSentenceRef.current = null;
    connectWebSocket(sessionId);
    loadHistory(sessionId);

    return () => {
      clearReconnectTimer();
      closeSocketQuietly(wsRef.current);
      wsRef.current = null;
    };
  }, [
    sessionId,
    clearReconnectTimer,
    closeSocketQuietly,
    connectWebSocket,
    finishStreamingMessage,
    loadHistory,
  ]);

  useEffect(() => {
    const onSessionChanged = (evt: Event) => {
      const customEvt = evt as CustomEvent<{ sessionId: string }>;
      const nextId = customEvt.detail?.sessionId;
      if (nextId && nextId !== sessionId) {
        setSessionId(nextId);
      }
    };
    window.addEventListener(SESSION_EVENT, onSessionChanged as EventListener);
    return () => window.removeEventListener(SESSION_EVENT, onSessionChanged as EventListener);
  }, [sessionId]);

  useEffect(() => {
    return () => {
      clearReconnectTimer();
      closeSocketQuietly(wsRef.current);
    };
  }, [clearReconnectTimer, closeSocketQuietly]);

  useEffect(() => {
    if (!listRef.current) return;
    if (!shouldAutoScrollRef.current) return;
    listRef.current.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const updateAutoScrollIntent = useCallback(() => {
    const element = listRef.current;
    if (!element) return;
    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    shouldAutoScrollRef.current = distanceFromBottom < 160;
  }, []);

  const sendMessage = useCallback(() => {
    const text = input.trim();
    if (!text || isSending || !sessionId) {
      return;
    }

    setMessages((prev) => [...prev, { id: makeId("user"), role: "user", content: text }]);
    setInput("");
    setIsSending(true);
    pendingMessageRef.current = text;

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "text_input", message: text }));
      pendingMessageRef.current = null;
      return;
    }

    if (sessionId) {
      connectWebSocket(sessionId);
    }
  }, [connectWebSocket, input, isSending, sessionId]);

  const blobToBase64 = useCallback(async (blob: Blob): Promise<string> => {
    const buffer = await blob.arrayBuffer();
    let binary = "";
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000;

    for (let index = 0; index < bytes.length; index += chunkSize) {
      const chunk = bytes.subarray(index, index + chunkSize);
      binary += String.fromCharCode(...chunk);
    }

    return window.btoa(binary);
  }, []);

  const mimeToFormat = useCallback((mimeType: string): string => {
    if (mimeType.includes("webm")) return "webm";
    if (mimeType.includes("ogg")) return "ogg";
    if (mimeType.includes("mp4")) return "m4a";
    if (mimeType.includes("wav")) return "wav";
    return "webm";
  }, []);

  const sendAudioBlob = useCallback(
    async (blob: Blob) => {
      if (!sessionId || blob.size === 0) {
        setIsTranscribing(false);
        return;
      }

      try {
        const audio = await blobToBase64(blob);
        pendingAudioRef.current = {
          audio,
          format: mimeToFormat(blob.type),
        };
        setIsSending(true);
        setIsTranscribing(true);
        audioResponseChunksRef.current = [];
        playedAudioChunkCountRef.current = 0;
        currentAudioSentenceRef.current = null;

        if (wsRef.current?.readyState === WebSocket.OPEN) {
          sendPendingAudio(wsRef.current);
          return;
        }

        connectWebSocket(sessionId);
      } catch {
        setIsSending(false);
        setIsTranscribing(false);
        setVoiceError("Could not prepare the recording. Please try again.");
      }
    },
    [blobToBase64, connectWebSocket, mimeToFormat, sendPendingAudio, sessionId],
  );

  const stopRecording = useCallback((send: boolean) => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;

    cancelRecordingRef.current = !send;
    recorder.stop();
    setIsRecording(false);
  }, []);

  const startRecording = useCallback(async () => {
    if (isRecording || isSending || !sessionId) return;

    setVoiceError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setVoiceError("Voice recording is not supported in this browser.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferredMime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"].find(
        (candidate) => MediaRecorder.isTypeSupported(candidate),
      );
      const recorder = new MediaRecorder(
        stream,
        preferredMime ? { mimeType: preferredMime } : undefined,
      );

      recordingChunksRef.current = [];
      cancelRecordingRef.current = false;
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          recordingChunksRef.current.push(event.data);
        }
      };

      recorder.onerror = () => {
        stream.getTracks().forEach((track) => track.stop());
        setIsRecording(false);
        setIsTranscribing(false);
        setVoiceError("Recording failed. Please try again.");
      };

      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const chunks = recordingChunksRef.current;
        recordingChunksRef.current = [];

        if (cancelRecordingRef.current || chunks.length === 0) {
          setIsTranscribing(false);
          return;
        }

        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        void sendAudioBlob(blob);
      };

      recorder.start();
      setIsRecording(true);
    } catch (error) {
      setIsRecording(false);
      setIsTranscribing(false);
      setVoiceError(
        error instanceof DOMException && error.name === "NotAllowedError"
          ? "Microphone permission was denied."
          : "Could not access the microphone.",
      );
    }
  }, [isRecording, isSending, sendAudioBlob, sessionId]);

  const toggleRecording = useCallback(() => {
    if (isRecording) {
      stopRecording(true);
      return;
    }

    void startRecording();
  }, [isRecording, startRecording, stopRecording]);

  const connectionLabel = useMemo(() => (connected ? "online" : "offline"), [connected]);
  const sessionLabel = mounted && sessionId ? sessionId.slice(0, 8) : "Session";
  const canSend = Boolean(sessionId && input.trim().length > 0 && !isSending && !isRecording);

  return (
    <main className="relative flex h-full min-w-0 flex-1 flex-col">
      <header className="hairline-b relative z-10 flex h-14 shrink-0 items-center gap-3 px-8">
        <div className="flex items-center gap-2.5">
          <span
            className={`flex h-2 w-2 rounded-full ${connected ? "bg-success" : "bg-destructive"} shadow-glow-sm`}
          />
          <h1 className="font-display text-[15px] font-medium tracking-tight text-foreground">
            SEC Investment Assistant
          </h1>
          <span className="rounded-md border border-border bg-secondary/40 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            {sessionLabel}
          </span>
        </div>

        <div className="ml-auto flex items-center gap-1">
          <ModelPill />
          <button
            onClick={toggleTheme}
            aria-label="Toggle theme"
            className="rounded-lg p-2 text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground"
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4" strokeWidth={1.75} />
            ) : (
              <Moon className="h-4 w-4" strokeWidth={1.75} />
            )}
          </button>
          <button
            onClick={onToggleIntelligence}
            aria-label="Toggle intelligence panel"
            aria-pressed={intelligenceOpen}
            className={[
              "group relative ml-1 flex h-9 items-center gap-1.5 overflow-hidden rounded-lg border px-2.5 py-1.5 text-[11px] font-medium transition",
              intelligenceOpen
                ? "border-primary/50 bg-gradient-accent-soft text-primary shadow-glow-sm"
                : "border-border bg-secondary/40 text-muted-foreground hover:border-primary/30 hover:text-foreground",
            ].join(" ")}
          >
            <AudioLines className="h-4 w-4" strokeWidth={1.75} />
            <span className="hidden sm:inline">Intelligence</span>
          </button>
        </div>
      </header>

      <div
        className="relative flex-1 overflow-y-auto"
        ref={listRef}
        onScroll={updateAutoScrollIntent}
      >
        <div
          className="pointer-events-none absolute inset-0 bg-aurora opacity-70 animate-ambient"
          aria-hidden
        />
        <div className="relative mx-auto w-full max-w-[820px] px-8 pb-48 pt-10">
          {messages.length === 0 && (
            <div className="mx-auto max-w-[680px] rounded-2xl border border-border bg-card/40 p-5 text-sm text-muted-foreground">
              Ask filing and market questions. Example: "Summarize AAPL 2023 10-K risk factors."
            </div>
          )}

          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              role={msg.role}
              content={msg.content}
              streaming={msg.streaming}
              audio={msg.audio}
              mimeType={msg.mimeType}
              onReplay={playAudioBlob}
            />
          ))}

          {lastLatency && (
            <div className="ml-11 mt-4 rounded-xl border border-border bg-card/40 p-3 text-[12px] text-muted-foreground">
              {Object.entries(lastLatency).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4">
                  <span>{k}</span>
                  <span className="font-mono">{Number(v).toFixed(1)} ms</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="pointer-events-none absolute inset-x-0 bottom-0 px-4 pb-4 sm:px-8 sm:pb-6">
        <div className="pointer-events-auto mx-auto w-full max-w-[820px]">
          <div className="relative">
            <form
              className="relative rounded-[20px] border border-border-strong bg-surface-elevated/90 shadow-panel backdrop-blur-xl"
              onSubmit={(e) => {
                e.preventDefault();
                sendMessage();
              }}
            >
              <div className="flex flex-wrap items-center gap-1.5 border-b border-border/60 px-4 py-2.5">
                {(isRecording || isTranscribing || voiceError) && (
                  <div
                    className={[
                      "flex items-center gap-2 rounded-md px-2 py-1 text-[11px]",
                      voiceError
                        ? "bg-destructive/10 text-destructive"
                        : "bg-secondary/40 text-muted-foreground",
                    ].join(" ")}
                    role={voiceError ? "alert" : "status"}
                  >
                    {isRecording && (
                      <span className="h-1.5 w-1.5 rounded-full bg-destructive animate-blink" />
                    )}
                    <span>
                      {voiceError ? voiceError : isRecording ? "Recording..." : "Transcribing..."}
                    </span>
                    {isRecording && (
                      <button
                        type="button"
                        onClick={() => stopRecording(false)}
                        className="ml-1 rounded p-0.5 text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
                        aria-label="Cancel recording"
                      >
                        <XCircle className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                )}
                <div className="ml-auto flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-success" : isReconnecting ? "bg-amber-400" : "bg-destructive"} ${connected ? "animate-blink" : ""}`}
                  />
                  <span>{isReconnecting ? "reconnecting" : connectionLabel}</span>
                </div>
              </div>

              <div className="flex items-end gap-2 px-4 py-3">
                <button
                  type="button"
                  className="rounded-lg p-2 text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                  aria-label="Attach file"
                  disabled
                >
                  <Paperclip className="h-4 w-4" strokeWidth={1.75} />
                </button>
                <button
                  type="button"
                  onClick={toggleRecording}
                  disabled={isSending && !isRecording}
                  className={[
                    "rounded-lg p-2 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
                    isRecording
                      ? "bg-destructive/15 text-destructive hover:bg-destructive/20"
                      : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                  ].join(" ")}
                  aria-label={isRecording ? "Stop recording" : "Start voice recording"}
                  aria-pressed={isRecording}
                >
                  {isRecording ? (
                    <Square className="h-4 w-4" strokeWidth={2} />
                  ) : (
                    <Mic className="h-4 w-4" strokeWidth={1.75} />
                  )}
                </button>
                <textarea
                  rows={1}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      sendMessage();
                    }
                  }}
                  disabled={isRecording}
                  placeholder={
                    isRecording
                      ? "Listening..."
                      : "Ask about SEC filings, financials, tools, and market data..."
                  }
                  className="min-h-[42px] flex-1 resize-none bg-transparent py-2 text-[14px] leading-6 text-foreground placeholder:text-muted-foreground focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={!canSend}
                  className="group relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-primary text-primary-foreground shadow-glow-sm transition hover:scale-105 hover:shadow-glow active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="Send message"
                >
                  {isSending ? (
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary-foreground/60 border-t-transparent" />
                  ) : (
                    <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </main>
  );
}

function ModelPill() {
  return (
    <button className="flex items-center gap-2 rounded-lg border border-border bg-secondary/40 px-2.5 py-1.5 text-xs text-foreground transition hover:bg-secondary/70">
      <Sparkles className="h-3 w-3 text-primary" />
      <span className="font-medium">llama3.2:3b</span>
      <ChevronDown className="h-3 w-3 text-muted-foreground" />
    </button>
  );
}

type MarkdownBlock =
  | { type: "code"; content: string; language: string }
  | { type: "paragraph"; content: string }
  | { type: "list"; items: string[] };

function parseMarkdownBlocks(markdown: string): MarkdownBlock[] {
  const normalized = markdown.replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let codeLines: string[] = [];
  let codeLanguage = "";
  let inCode = false;

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    blocks.push({ type: "paragraph", content: paragraph.join(" ").trim() });
    paragraph = [];
  };

  const flushList = () => {
    if (listItems.length === 0) return;
    blocks.push({ type: "list", items: listItems });
    listItems = [];
  };

  for (const line of lines) {
    const fence = line.match(/^```(\w+)?\s*$/);
    if (fence) {
      if (inCode) {
        blocks.push({ type: "code", content: codeLines.join("\n"), language: codeLanguage });
        codeLines = [];
        codeLanguage = "";
        inCode = false;
      } else {
        flushParagraph();
        flushList();
        inCode = true;
        codeLanguage = fence[1] ?? "";
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }

    const listMatch = line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)$/);
    if (listMatch) {
      flushParagraph();
      listItems.push(listMatch[1] ?? "");
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    flushList();
    paragraph.push(line.trim());
  }

  if (inCode) {
    blocks.push({ type: "code", content: codeLines.join("\n"), language: codeLanguage });
  }
  flushParagraph();
  flushList();

  return blocks;
}

function InlineMarkdown({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g);

  return (
    <>
      {parts.map((part, index) => {
        if (!part) return null;

        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code
              key={index}
              className="rounded bg-secondary/60 px-1 py-0.5 font-mono text-[0.92em]"
            >
              {part.slice(1, -1)}
            </code>
          );
        }

        if (part.startsWith("**") && part.endsWith("**")) {
          return (
            <strong key={index} className="font-semibold text-foreground">
              {part.slice(2, -2)}
            </strong>
          );
        }

        const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        if (link) {
          return (
            <a
              key={index}
              href={link[2] ?? "#"}
              target="_blank"
              rel="noreferrer"
              className="text-primary underline decoration-primary/40 underline-offset-4"
            >
              {link[1] ?? part}
            </a>
          );
        }

        return <Fragment key={index}>{part}</Fragment>;
      })}
    </>
  );
}

function MarkdownMessage({ content }: { content: string }) {
  const blocks = parseMarkdownBlocks(content);

  if (blocks.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      {blocks.map((block, index) => {
        if (block.type === "code") {
          return (
            <pre
              key={index}
              className="overflow-x-auto rounded-lg border border-border bg-secondary/40 p-3 text-[13px] leading-6"
            >
              <code>{block.content}</code>
            </pre>
          );
        }

        if (block.type === "list") {
          return (
            <ul key={index} className="ml-5 list-disc space-y-1">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>
                  <InlineMarkdown text={item} />
                </li>
              ))}
            </ul>
          );
        }

        return (
          <p key={index}>
            <InlineMarkdown text={block.content} />
          </p>
        );
      })}
    </div>
  );
}

function MessageBubble({
  role,
  content,
  streaming,
  audio,
  mimeType,
  onReplay,
}: {
  role: ChatMessage["role"];
  content: string;
  streaming?: boolean;
  audio?: string;
  mimeType?: string;
  onReplay: (audioBase64: string, mimeType?: string) => void;
}) {
  if (role === "user") {
    return (
      <div className="mb-6 flex justify-end animate-fade-up">
        <div className="max-w-[85%] rounded-2xl rounded-tr-md border border-border bg-secondary/50 px-4 py-3 text-[14px] leading-7 text-foreground">
          {content}
        </div>
      </div>
    );
  }

  const isSystem = role === "system";
  return (
    <div className="mb-6 flex gap-4 animate-fade-up">
      <div
        className={`relative mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${isSystem ? "bg-destructive/60" : "bg-gradient-primary"} shadow-glow-sm`}
      >
        <Sparkles className="h-3.5 w-3.5 text-primary-foreground" strokeWidth={2.5} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-2 flex items-center gap-2 text-[12px] font-medium text-foreground">
          <span>{isSystem ? "System" : "ARBOR-AI"}</span>
          {!isSystem && audio && (
            <button
              type="button"
              onClick={() => onReplay(audio, mimeType)}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-secondary/30 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground transition hover:border-primary/30 hover:text-foreground"
              aria-label="Replay assistant audio"
            >
              <Volume2 className="h-3 w-3" />
              Replay
            </button>
          )}
          {!isSystem && streaming && (
            <span className="rounded-md bg-secondary/30 px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">
              speaking
            </span>
          )}
        </div>
        <div className="text-[14.5px] leading-7 text-foreground/90">
          {content ? <MarkdownMessage content={content} /> : <TypingIndicator />}
          {streaming && content && (
            <span className="ml-1 inline-block h-4 w-1 translate-y-0.5 rounded-full bg-primary/70 animate-blink" />
          )}
        </div>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1.5 py-1" aria-label="Assistant is typing">
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60 animate-blink" />
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/50 animate-blink [animation-delay:120ms]" />
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-blink [animation-delay:240ms]" />
    </div>
  );
}
