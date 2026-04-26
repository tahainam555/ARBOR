import { useEffect, useRef } from "react";
import {
  Activity,
  Cpu,
  Database,
  Gauge,
  Radio,
  Sparkles,
  Zap,
  ChevronRight,
  Network,
  ListTodo,
  X,
} from "lucide-react";

interface IntelligencePanelProps {
  open: boolean;
  onClose: () => void;
}

export function IntelligencePanel({ open, onClose }: IntelligencePanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  // ESC to close + lock scroll while open
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  return (
    <div
      aria-hidden={!open}
      className={[
        "fixed inset-0 z-50",
        open ? "pointer-events-auto" : "pointer-events-none",
      ].join(" ")}
    >
      {/* Backdrop: blur + dim */}
      <button
        aria-label="Close intelligence panel"
        onClick={onClose}
        tabIndex={open ? 0 : -1}
        className={[
          "absolute inset-0 cursor-default bg-background/40 backdrop-blur-md transition-all duration-500",
          open ? "opacity-100" : "opacity-0",
        ].join(" ")}
        style={{ WebkitBackdropFilter: "blur(14px) saturate(140%)" }}
      />

      {/* Slide-over panel */}
      <aside
        ref={panelRef}
        role="dialog"
        aria-label="Intelligence observability panel"
        className={[
          "absolute right-0 top-0 flex h-full w-full max-w-[380px] flex-col overflow-hidden",
          "border-l border-border bg-surface-glass shadow-panel ring-1 ring-white/5",
          "transition-transform duration-500",
          open ? "translate-x-0" : "translate-x-full",
        ].join(" ")}
        style={{
          transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
          backdropFilter: "blur(24px) saturate(160%)",
          WebkitBackdropFilter: "blur(24px) saturate(160%)",
        }}
      >
        {/* Soft inner glow border */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-l-2xl"
          style={{
            boxShadow:
              "inset 1px 0 0 oklch(0.78 0.16 200 / 0.08), inset 0 1px 0 oklch(1 0 0 / 0.04)",
          }}
        />
        {/* Ambient gradient accent */}
        <div
          aria-hidden
          className="pointer-events-none absolute -top-32 right-0 h-64 w-64 rounded-full bg-primary/10 blur-3xl"
        />

        {/* Header */}
        <div className="hairline-b sticky top-0 z-10 flex h-14 items-center gap-2 bg-surface/50 px-5 backdrop-blur-xl">
          <Activity className="h-3.5 w-3.5 text-primary" />
          <span className="font-display text-[13px] font-medium text-foreground">
            Intelligence
          </span>
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
          {/* Hero metric */}
          <PanelCard>
            <div className="flex items-start justify-between">
              <div>
                <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  p95 latency
                </div>
                <div className="mt-1 flex items-baseline gap-1">
                  <span className="font-display text-3xl font-semibold text-foreground">
                    142
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">ms</span>
                </div>
                <div className="mt-1 flex items-center gap-1.5 text-[11px]">
                  <span className="text-success">▼ 18%</span>
                  <span className="text-muted-foreground">vs 24h</span>
                </div>
              </div>
              <Gauge className="h-4 w-4 text-primary" />
            </div>
            <Sparkline />
          </PanelCard>

          {/* Metric grid */}
          <div className="grid grid-cols-2 gap-2.5">
            <MiniMetric icon={<Database className="h-3 w-3" />} label="Retrieval" value="38" unit="ms" trend="−6%" good />
            <MiniMetric icon={<Cpu className="h-3 w-3" />} label="Memory" value="62" unit="%" trend="stable" />
            <MiniMetric icon={<Zap className="h-3 w-3" />} label="Throughput" value="2.4k" unit="t/s" trend="+12%" good />
            <MiniMetric icon={<Radio className="h-3 w-3" />} label="WebSocket" value="14" unit="ms" trend="ok" good />
          </div>

          {/* Reasoning */}
          <PanelCard
            title="AI reasoning"
            icon={<Sparkles className="h-3 w-3 text-primary" />}
            right={<span className="font-mono text-[10px] text-muted-foreground">step 4 / 4</span>}
          >
            <ul className="space-y-2 text-[12px]">
              {[
                { label: "Parse query intent", state: "done", time: "84ms" },
                { label: "Retrieve context (4 sources)", state: "done", time: "312ms" },
                { label: "Cross-reference memory", state: "done", time: "128ms" },
                { label: "Synthesize response", state: "active", time: "—" },
              ].map((step) => (
                <li key={step.label} className="flex items-center gap-2.5">
                  <StepDot state={step.state as "done" | "active"} />
                  <span className={step.state === "active" ? "text-foreground" : "text-muted-foreground"}>
                    {step.label}
                  </span>
                  <span className="ml-auto font-mono text-[10px] text-muted-foreground">{step.time}</span>
                </li>
              ))}
            </ul>
          </PanelCard>

          {/* Sessions */}
          <PanelCard
            title="Active sessions"
            icon={<Network className="h-3 w-3 text-primary" />}
            right={<span className="font-mono text-[10px] text-muted-foreground">7</span>}
          >
            <div className="space-y-2.5">
              {[
                { name: "arbor · prod-eu", load: 72, color: "bg-primary" },
                { name: "arbor · prod-us", load: 54, color: "bg-accent" },
                { name: "arbor · staging", load: 28, color: "bg-success" },
              ].map((s) => (
                <div key={s.name}>
                  <div className="mb-1 flex items-center justify-between text-[11px]">
                    <span className="font-mono text-muted-foreground">{s.name}</span>
                    <span className="font-mono text-foreground">{s.load}%</span>
                  </div>
                  <div className="h-1 overflow-hidden rounded-full bg-secondary/60">
                    <div
                      className={`h-full rounded-full ${s.color} shadow-glow-sm`}
                      style={{ width: `${s.load}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </PanelCard>

          {/* Queue health */}
          <PanelCard title="Queue health" icon={<ListTodo className="h-3 w-3 text-primary" />}>
            <div className="grid grid-cols-3 gap-2 text-center">
              {[
                { label: "Pending", value: "12", color: "text-foreground" },
                { label: "Running", value: "3", color: "text-primary" },
                { label: "Failed", value: "0", color: "text-success" },
              ].map((q) => (
                <div key={q.label}>
                  <div className={`font-display text-xl font-semibold ${q.color}`}>{q.value}</div>
                  <div className="mt-0.5 text-[10px] text-muted-foreground">{q.label}</div>
                </div>
              ))}
            </div>
          </PanelCard>

          <button className="group flex w-full items-center justify-between rounded-xl border border-border bg-card/40 px-4 py-2.5 text-[12px] text-muted-foreground transition hover:bg-card/70 hover:text-foreground">
            Open full observability
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
  right,
  children,
}: {
  title?: string;
  icon?: React.ReactNode;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-border bg-card/50 p-4 shadow-elevated backdrop-blur-sm">
      {title && (
        <div className="mb-3 flex items-center gap-1.5">
          {icon}
          <span className="text-[11px] font-medium text-foreground">{title}</span>
          {right && <span className="ml-auto">{right}</span>}
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

function StepDot({ state }: { state: "done" | "active" }) {
  if (state === "active") {
    return (
      <span className="relative flex h-2 w-2 shrink-0">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-50" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-primary shadow-glow-sm" />
      </span>
    );
  }
  return <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-success/70" />;
}

function Sparkline() {
  const points = [42, 38, 50, 44, 36, 48, 40, 32, 38, 30, 34, 28, 30, 24, 26];
  const w = 280;
  const h = 56;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const step = w / (points.length - 1);
  const path = points
    .map((p, i) => {
      const x = i * step;
      const y = h - ((p - min) / (max - min)) * h;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const area = `${path} L${w},${h} L0,${h} Z`;

  return (
    <div className="mt-3">
      <svg viewBox={`0 0 ${w} ${h}`} className="h-14 w-full overflow-visible">
        <defs>
          <linearGradient id="spark-stroke" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="oklch(0.7 0.14 220)" />
            <stop offset="100%" stopColor="oklch(0.85 0.14 190)" />
          </linearGradient>
          <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="oklch(0.78 0.16 200 / 0.35)" />
            <stop offset="100%" stopColor="oklch(0.78 0.16 200 / 0)" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#spark-fill)" />
        <path
          d={path}
          fill="none"
          stroke="url(#spark-stroke)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="animate-graph"
          style={{ filter: "drop-shadow(0 0 6px oklch(0.78 0.16 200 / 0.6))" }}
        />
      </svg>
    </div>
  );
}
