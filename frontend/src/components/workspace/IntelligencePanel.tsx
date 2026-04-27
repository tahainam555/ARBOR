import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Cpu,
  Database,
  Gauge,
  Radio,
  Zap,
  ChevronRight,
  Network,
  ListTodo,
  X,
} from "lucide-react";
import { backendBaseUrl } from "@/lib/backend";

interface IntelligencePanelProps {
  open: boolean;
  onClose: () => void;
}

type GlobalLatency = Record<string, number>;

type ConcurrencyMetrics = {
  max_concurrent_turns: number;
  current_active_turns: number;
  queued_sessions: number;
  total_turns_processed: number;
  total_wait_ms: number;
};

export function IntelligencePanel({ open, onClose }: IntelligencePanelProps) {
  const [latency, setLatency] = useState<GlobalLatency>({});
  const [concurrency, setConcurrency] = useState<ConcurrencyMetrics | null>(null);

  useEffect(() => {
    if (!open) return;

    const fetchMetrics = async () => {
      try {
        const [latRes, concRes] = await Promise.all([
          fetch(`${backendBaseUrl()}/api/latency/global`),
          fetch(`${backendBaseUrl()}/api/metrics/concurrency`),
        ]);

        if (latRes.ok) {
          const lat = (await latRes.json()) as { averages?: GlobalLatency };
          setLatency(lat.averages ?? {});
        }

        if (concRes.ok) {
          const conc = (await concRes.json()) as ConcurrencyMetrics;
          setConcurrency(conc);
        }
      } catch {
        // Ignore transient metric polling failures.
      }
    };

    fetchMetrics();
    const timer = window.setInterval(fetchMetrics, 4000);
    return () => window.clearInterval(timer);
  }, [open]);

  const p95Like = useMemo(() => {
    const values = Object.values(latency).filter((v) => Number.isFinite(v));
    if (values.length === 0) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const idx = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95));
    return sorted[idx];
  }, [latency]);

  return (
    <div
      aria-hidden={!open}
      className={[
        "fixed inset-0 z-50",
        open ? "pointer-events-auto" : "pointer-events-none",
      ].join(" ")}
    >
      <button
        aria-label="Close intelligence panel"
        onClick={onClose}
        tabIndex={open ? 0 : -1}
        className={[
          "absolute inset-0 cursor-default bg-background/40 backdrop-blur-md transition-all duration-500",
          open ? "opacity-100" : "opacity-0",
        ].join(" ")}
      />

      <aside
        role="dialog"
        aria-label="Intelligence observability panel"
        className={[
          "absolute right-0 top-0 flex h-full w-full max-w-[380px] flex-col overflow-hidden",
          "border-l border-border bg-surface-glass shadow-panel ring-1 ring-white/5",
          "transition-transform duration-500",
          open ? "translate-x-0" : "translate-x-full",
        ].join(" ")}
      >
        <div className="hairline-b sticky top-0 z-10 flex h-14 items-center gap-2 bg-surface/50 px-5 backdrop-blur-xl">
          <Activity className="h-3.5 w-3.5 text-primary" />
          <span className="font-display text-[13px] font-medium text-foreground">Intelligence</span>
          <span className="ml-3 flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-success animate-blink" />
            live
          </span>
          <button
            onClick={onClose}
            aria-label="Close panel"
            className="ml-auto rounded-md p-1.5 text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground"
          >
            <X className="h-4 w-4" strokeWidth={1.75} />
          </button>
        </div>

        <div className="relative space-y-4 overflow-y-auto px-4 py-5">
          <PanelCard>
            <div className="flex items-start justify-between">
              <div>
                <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  latency snapshot
                </div>
                <div className="mt-1 flex items-baseline gap-1">
                  <span className="font-display text-3xl font-semibold text-foreground">
                    {Number(p95Like).toFixed(0)}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">ms</span>
                </div>
                <div className="mt-1 text-[11px] text-muted-foreground">approx p95 from stage averages</div>
              </div>
              <Gauge className="h-4 w-4 text-primary" />
            </div>
          </PanelCard>

          <div className="grid grid-cols-2 gap-2.5">
            <MiniMetric icon={<Database className="h-3 w-3" />} label="Stages" value={`${Object.keys(latency).length}`} unit="count" trend="live" good />
            <MiniMetric icon={<Cpu className="h-3 w-3" />} label="Queue" value={`${concurrency?.queued_sessions ?? 0}`} unit="sessions" trend="live" />
            <MiniMetric icon={<Zap className="h-3 w-3" />} label="Turns" value={`${concurrency?.total_turns_processed ?? 0}`} unit="total" trend="live" good />
            <MiniMetric icon={<Radio className="h-3 w-3" />} label="Active" value={`${concurrency?.current_active_turns ?? 0}`} unit="turns" trend={`max ${concurrency?.max_concurrent_turns ?? 0}`} good />
          </div>

          <PanelCard title="Latency by stage" icon={<Network className="h-3 w-3 text-primary" />}>
            <div className="space-y-2.5">
              {Object.entries(latency).map(([name, value]) => (
                <div key={name}>
                  <div className="mb-1 flex items-center justify-between text-[11px]">
                    <span className="font-mono text-muted-foreground">{name}</span>
                    <span className="font-mono text-foreground">{Number(value).toFixed(1)} ms</span>
                  </div>
                  <div className="h-1 overflow-hidden rounded-full bg-secondary/60">
                    <div
                      className="h-full rounded-full bg-primary shadow-glow-sm"
                      style={{ width: `${Math.min(100, Number(value) / 12)}%` }}
                    />
                  </div>
                </div>
              ))}
              {Object.keys(latency).length === 0 && (
                <div className="text-[12px] text-muted-foreground">No latency data yet.</div>
              )}
            </div>
          </PanelCard>

          <PanelCard title="Queue health" icon={<ListTodo className="h-3 w-3 text-primary" />}>
            <div className="grid grid-cols-3 gap-2 text-center">
              <MetricBlock label="Pending" value={`${concurrency?.queued_sessions ?? 0}`} color="text-foreground" />
              <MetricBlock label="Running" value={`${concurrency?.current_active_turns ?? 0}`} color="text-primary" />
              <MetricBlock label="Capacity" value={`${concurrency?.max_concurrent_turns ?? 0}`} color="text-success" />
            </div>
            <div className="mt-3 text-[11px] text-muted-foreground">
              Total wait: {Number(concurrency?.total_wait_ms ?? 0).toFixed(1)} ms
            </div>
          </PanelCard>

          <button className="group flex w-full items-center justify-between rounded-xl border border-border bg-card/40 px-4 py-2.5 text-[12px] text-muted-foreground transition hover:bg-card/70 hover:text-foreground">
            Metrics endpoint connected
            <ChevronRight className="h-3.5 w-3.5 transition group-hover:translate-x-0.5" />
          </button>
        </div>
      </aside>
    </div>
  );
}

function PanelCard({
  title,
  icon,
  children,
}: {
  title?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-border bg-card/50 p-4 shadow-elevated backdrop-blur-sm">
      {title && (
        <div className="mb-3 flex items-center gap-1.5">
          {icon}
          <span className="text-[11px] font-medium text-foreground">{title}</span>
        </div>
      )}
      {children}
    </div>
  );
}

function MiniMetric({
  icon,
  label,
  value,
  unit,
  trend,
  good,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  unit: string;
  trend: string;
  good?: boolean;
}) {
  return (
    <div className="rounded-xl border border-border bg-card/40 p-3 transition hover:border-border-strong hover:bg-card/60">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="font-display text-lg font-semibold text-foreground">{value}</span>
        <span className="font-mono text-[10px] text-muted-foreground">{unit}</span>
      </div>
      <div className={`mt-0.5 text-[10px] ${good ? "text-success" : "text-muted-foreground"}`}>
        {trend}
      </div>
    </div>
  );
}

function MetricBlock({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div className={`font-display text-xl font-semibold ${color}`}>{value}</div>
      <div className="mt-0.5 text-[10px] text-muted-foreground">{label}</div>
    </div>
  );
}
