const SESSION_KEY = "sec_assistant_session_id";

export function backendBaseUrl(): string {
  const backendPort = import.meta.env.VITE_BACKEND_PORT ?? "8000";

  if (typeof window === "undefined") {
    return `http://127.0.0.1:${backendPort}`;
  }

  if (window.location.protocol === "file:") {
    return `http://127.0.0.1:${backendPort}`;
  }

  if (!window.location.port || window.location.port === backendPort) {
    return `${window.location.protocol}//${window.location.host}`;
  }

  return `${window.location.protocol}//${window.location.hostname}:${backendPort}`;
}

export function websocketUrl(sessionId: string): string {
  const httpBase = backendBaseUrl();
  const wsBase = httpBase.replace("http://", "ws://").replace("https://", "wss://");
  return `${wsBase}/ws/${sessionId}`;
}

export function ensureSessionId(): string {
  if (typeof window === "undefined") {
    return "server-render-session";
  }

  let sessionId = window.localStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = window.crypto?.randomUUID?.() ?? `session-${Date.now()}`;
    window.localStorage.setItem(SESSION_KEY, sessionId);
  }
  return sessionId;
}

export function setCurrentSessionId(sessionId: string): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(SESSION_KEY, sessionId);
  }
}

export function getCurrentSessionId(): string {
  return ensureSessionId();
}
