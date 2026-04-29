import {
  ArrowUp,
  Paperclip,
  Sparkles,
  ChevronDown,
  AudioLines,
  Sun,
  Moon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

  const wsRef = useRef<WebSocket | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const pendingMessageRef = useRef<string | null>(null);
  const socketGenerationRef = useRef(0);
  const mountedRef = useRef(false);
  const sessionRef = useRef<string>("");

  useEffect(() => {
    mountedRef.current = true;
    setMounted(true);
    setSessionId(getCurrentSessionId());
    return () => {
      mountedRef.current = false;
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

  function scheduleReconnect(targetSessionId: string) {
    clearReconnectTimer();
    setIsReconnecting(true);
    reconnectTimerRef.current = window.setTimeout(() => {
      reconnectTimerRef.current = null;
      connectWebSocket(targetSessionId);
    }, 1200);
  }

  const safelySetConnected = useCallback((value: boolean, generation: number) => {
    if (socketGenerationRef.current !== generation || !mountedRef.current) {
      return;
    }
    setConnected(value);
  }, []);

  function connectWebSocket(targetSessionId: string) {
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
    };

    ws.onclose = () => {
      safelySetConnected(false, generation);
      // Only trigger reconnect if socket is still current generation
      if (socketGenerationRef.current === generation && mountedRef.current && wsRef.current === ws) {
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
          latency_breakdown?: Record<string, number>;
        };

        if (msg.type === "text_chunk") {
          setMessages((prev) => {
            const sid = streamingId ?? makeId("assistant");
            if (!streamingId) {
              setStreamingId(sid);
              return [...prev, { id: sid, role: "assistant", content: msg.content ?? "" }];
            }
            return prev.map((m) => (m.id === sid ? { ...m, content: `${m.content}${msg.content ?? ""}` } : m));
          });
          return;
        }

        if (msg.type === "turn_complete") {
          setIsSending(false);
          setStreamingId(null);
          setIsReconnecting(false);
          if (msg.latency_breakdown) {
            setLastLatency(msg.latency_breakdown);
          }
          window.dispatchEvent(new Event("arbor-refresh-sessions"));
          return;
        }

        if (msg.type === "error") {
          setIsSending(false);
          setStreamingId(null);
          setIsReconnecting(false);
          setMessages((prev) => [...prev, { id: makeId("system"), role: "system", content: `Error: ${msg.message ?? "Unknown error"}` }]);
        }
      } catch {
        setMessages((prev) => [...prev, { id: makeId("system"), role: "system", content: "Received unexpected server payload." }]);
      }
    };
  }


  const loadHistory = useCallback(async (targetSessionId: string) => {
    try {
      const res = await fetch(`${backendBaseUrl()}/api/sessions/${targetSessionId}/history`);
      if (!res.ok) throw new Error(`Failed to load history (${res.status})`);
      const data = (await res.json()) as {
        messages?: Array<{ role?: string; message?: string; text?: string; content?: string }>;
      };
      const normalized = (data.messages ?? []).map((m, idx) => ({
        id: makeId(`history-${idx}`),
        role: (m.role === "user" || m.role === "assistant" ? m.role : "system") as ChatMessage["role"],
        content: m.message ?? m.text ?? m.content ?? "",
      }));
      setMessages(normalized);
    } catch {
      setMessages([{ id: makeId("system"), role: "system", content: "Unable to load session history." }]);
    }
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    sessionRef.current = sessionId;
    setMessages([]);
    setStreamingId(null);
    setIsSending(false);
    connectWebSocket(sessionId);
    loadHistory(sessionId);

    return () => {
      clearReconnectTimer();
      closeSocketQuietly(wsRef.current);
      wsRef.current = null;
    };
  }, [sessionId, clearReconnectTimer, loadHistory]);

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
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages]);

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
  }, [input, isSending, sessionId]);

  const connectionLabel = useMemo(() => (connected ? "online" : "offline"), [connected]);
  const sessionLabel = mounted && sessionId ? sessionId.slice(0, 8) : "Session";
  const canSend = Boolean(sessionId && input.trim().length > 0 && !isSending);

  return (
    <main className="relative flex h-full min-w-0 flex-1 flex-col">
      <header className="hairline-b relative z-10 flex h-14 shrink-0 items-center gap-3 px-8">
        <div className="flex items-center gap-2.5">
          <span className={`flex h-2 w-2 rounded-full ${connected ? "bg-success" : "bg-destructive"} shadow-glow-sm`} />
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

      <div className="relative flex-1 overflow-y-auto" ref={listRef}>
        <div className="pointer-events-none absolute inset-0 bg-aurora opacity-70 animate-ambient" aria-hidden />
        <div className="relative mx-auto w-full max-w-[820px] px-8 pb-48 pt-10">
          {messages.length === 0 && (
            <div className="mx-auto max-w-[680px] rounded-2xl border border-border bg-card/40 p-5 text-sm text-muted-foreground">
              Ask filing and market questions. Example: "Summarize AAPL 2023 10-K risk factors."
            </div>
          )}

          {messages.map((msg) => (
            <MessageBubble key={msg.id} role={msg.role} content={msg.content} />
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
                <div className="ml-auto flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
                  <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-success" : isReconnecting ? "bg-amber-400" : "bg-destructive"} ${connected ? "animate-blink" : ""}`} />
                  <span>{isReconnecting ? "reconnecting" : connectionLabel}</span>
                </div>
              </div>

              <div className="flex items-end gap-2 px-4 py-3">
                <button type="button" className="rounded-lg p-2 text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50" aria-label="Attach file" disabled>
                  <Paperclip className="h-4 w-4" strokeWidth={1.75} />
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
                  placeholder="Ask about SEC filings, financials, tools, and market data..."
                  className="min-h-[42px] flex-1 resize-none bg-transparent py-2 text-[14px] leading-6 text-foreground placeholder:text-muted-foreground focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={!canSend}
                  className="group relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-primary text-primary-foreground shadow-glow-sm transition hover:scale-105 hover:shadow-glow active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="Send message"
                >
                  {isSending ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary-foreground/60 border-t-transparent" /> : <ArrowUp className="h-4 w-4" strokeWidth={2.5} />}
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

function MessageBubble({ role, content }: { role: ChatMessage["role"]; content: string }) {
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
      <div className={`relative mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${isSystem ? "bg-destructive/60" : "bg-gradient-primary"} shadow-glow-sm`}>
        <Sparkles className="h-3.5 w-3.5 text-primary-foreground" strokeWidth={2.5} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-2 text-[12px] font-medium text-foreground">{isSystem ? "System" : "Assistant"}</div>
        <div className="whitespace-pre-wrap text-[14.5px] leading-7 text-foreground/90">{content}</div>
      </div>
    </div>
  );
}
