import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Plus,
  Search,
  MessageSquare,
  Database,
  Settings,
  Layers,
  Command,
  RefreshCw,
} from "lucide-react";
import { backendBaseUrl, getCurrentSessionId, setCurrentSessionId } from "@/lib/backend";

type SessionRecord = {
  session_id: string;
  title?: string | null;
  last_active?: string | null;
  turn_count?: number;
  summary?: string | null;
};

const SESSION_EVENT = "arbor-session-changed";

function formatTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "-";
  return date.toLocaleString();
}

export function Sidebar() {
  const [mounted, setMounted] = useState(false);
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string>("");

  const dispatchSessionChanged = useCallback((sessionId: string) => {
    setCurrentSessionId(sessionId);
    setActiveSessionId(sessionId);
    window.dispatchEvent(new CustomEvent(SESSION_EVENT, { detail: { sessionId } }));
  }, []);

  const refreshSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${backendBaseUrl()}/api/sessions`);
      if (!res.ok) throw new Error(`Failed to load sessions (${res.status})`);
      const data = (await res.json()) as SessionRecord[];
      const sorted = [...data].sort((a, b) => {
        const aTs = a.last_active ? new Date(a.last_active).valueOf() : 0;
        const bTs = b.last_active ? new Date(b.last_active).valueOf() : 0;
        return bTs - aTs;
      });
      setSessions(sorted);

      const exists = sorted.some((s) => s.session_id === activeSessionId);
      if (!exists && sorted.length > 0) {
        dispatchSessionChanged(sorted[0].session_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load sessions");
    } finally {
      setLoading(false);
    }
  }, [activeSessionId, dispatchSessionChanged]);

  const createSession = useCallback(async () => {
    setError(null);
    try {
      const sessionId = crypto.randomUUID();
      const res = await fetch(`${backendBaseUrl()}/api/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          title: `Conversation`,
        }),
      });
      if (!res.ok) throw new Error(`Failed to create session (${res.status})`);
      await refreshSessions();
      dispatchSessionChanged(sessionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create session");
    }
  }, [dispatchSessionChanged, refreshSessions]);

  useEffect(() => {
    setMounted(true);
    setActiveSessionId(getCurrentSessionId());
    refreshSessions();

    const interval = window.setInterval(refreshSessions, 15000);
    const onRefresh = () => refreshSessions();
    window.addEventListener("arbor-refresh-sessions", onRefresh);

    return () => {
      window.clearInterval(interval);
      window.removeEventListener("arbor-refresh-sessions", onRefresh);
    };
  }, [refreshSessions]);

  const filteredSessions = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return sessions;
    return sessions.filter((s) => {
      const haystack = `${s.title ?? ""} ${s.summary ?? ""} ${s.session_id}`.toLowerCase();
      return haystack.includes(term);
    });
  }, [query, sessions]);

  const currentSessionLabel = mounted && activeSessionId ? activeSessionId.slice(0, 12) : "Ready";

  return (
    <aside className="hairline-r relative flex h-full w-[300px] shrink-0 flex-col bg-sidebar/80">
      <div className="flex h-14 items-center gap-3 px-5">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-secondary/40">
          <Layers className="h-3.5 w-3.5 text-foreground" strokeWidth={2} />
        </div>
        <div className="flex flex-1 items-center gap-1.5">
          <span className="font-display text-[15px] font-semibold tracking-tight text-foreground">
            SEC Assistant
          </span>
        </div>
      </div>

      <div className="px-3 pb-2 pt-1">
        <button
          onClick={createSession}
          className="group flex w-full items-center gap-2 rounded-md border border-border bg-secondary/40 px-3 py-2 text-sm font-medium text-foreground transition hover:bg-secondary/60"
        >
          <Plus className="h-4 w-4" strokeWidth={1.75} />
          <span>New conversation</span>
          <span className="ml-auto flex items-center gap-1 rounded-md bg-transparent px-1 py-0.5 font-mono text-[10px] text-muted-foreground">
            <Command className="h-3 w-3" />
          </span>
        </button>
      </div>

      <div className="px-3 pb-3">
          <div className="group relative flex items-center gap-2 rounded-md border border-border bg-input/30 px-3 py-2 transition focus-within:border-primary/40 focus-within:bg-input/50">
          <Search className="h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sessions"
            className="flex-1 bg-transparent text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none"
          />
          <button onClick={refreshSessions} aria-label="Refresh sessions" className="rounded-md p-1 text-muted-foreground hover:bg-secondary/20">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-2">
        <SectionLabel>Sessions</SectionLabel>
        {error && (
          <div className="mb-2 rounded-lg border border-destructive/40 bg-destructive/10 px-2.5 py-2 text-[11px] text-destructive">
            {error}
          </div>
        )}

        <ul className="space-y-1">
          {filteredSessions.map((item) => {
            const isActive = item.session_id === activeSessionId;
            return (
              <li key={item.session_id}>
                <button onClick={() => dispatchSessionChanged(item.session_id)} className={navItemClass(isActive)}>
                  <MessageSquare
                    className={`h-3.5 w-3.5 shrink-0 ${isActive ? "text-primary" : "text-muted-foreground/70"}`}
                    strokeWidth={1.75}
                  />
                  <div className="min-w-0 flex-1 text-left">
                    <div className="truncate text-[12px] text-foreground">
                      {item.title || item.session_id.slice(0, 12)}
                    </div>
                    <div className="truncate text-[10px] text-muted-foreground">
                      {formatTime(item.last_active)} | turns {item.turn_count ?? 0}
                    </div>
                  </div>
                </button>
              </li>
            );
          })}
          {filteredSessions.length === 0 && (
            <li className="rounded-lg border border-border/50 px-3 py-2 text-[12px] text-muted-foreground">
              No sessions found.
            </li>
          )}
        </ul>
      </div>

      <div className="hairline-t mt-auto px-3 py-3">
        <div className="rounded-md border border-border bg-card/40 p-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Database className="h-3 w-3 text-muted-foreground" />
              <span className="text-[11px] font-medium text-foreground">Session Store</span>
            </div>
            <span className="font-mono text-[10px] text-muted-foreground">{sessions.length}</span>
          </div>
          <div className="relative h-1 overflow-hidden rounded-full bg-secondary/20">
            <div className="absolute inset-y-0 left-0 rounded-full bg-primary/40" style={{ width: `${Math.min(100, sessions.length * 8)}%` }} />
          </div>
          <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
            <span>active session tracked</span>
            <span className="font-mono">local</span>
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between px-1">
          <div className="leading-tight">
            <div className="text-[12px] font-medium text-foreground">SEC Assistant</div>
            <div className="text-[10px] text-muted-foreground">production workspace</div>
          </div>
          <button className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary/20">
            <Settings className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="mt-2 px-1 text-[10px] text-muted-foreground">session {currentSessionLabel}</div>
      </div>
    </aside>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 px-2.5 pb-1.5 pt-1 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground/70">
      {children}
    </div>
  );
}

function navItemClass(active: boolean) {
  return [
    "group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] transition",
    active
      ? "bg-secondary/80 text-foreground shadow-[inset_0_1px_0_oklch(1_0_0/0.04)]"
      : "text-muted-foreground hover:bg-secondary/40 hover:text-foreground",
  ].join(" ");
}
