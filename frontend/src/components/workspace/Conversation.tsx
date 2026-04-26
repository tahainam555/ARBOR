import {
  ArrowUp,
  Mic,
  Paperclip,
  Sparkles,
  Database,
  Globe,
  Wrench,
  Brain,
  ChevronDown,
  Copy,
  ThumbsUp,
  ThumbsDown,
  RotateCcw,
  ExternalLink,
  FileText,
  Code2,
  Share2,
  Star,
  AudioLines,
  Sun,
  Moon,
} from "lucide-react";
import { useState } from "react";
import { useTheme } from "@/components/theme/ThemeProvider";

interface ConversationProps {
  intelligenceOpen: boolean;
  onToggleIntelligence: () => void;
}

export function Conversation({ intelligenceOpen, onToggleIntelligence }: ConversationProps) {
  const { theme, toggle: toggleTheme } = useTheme();
  const [tools, setTools] = useState<Record<string, boolean>>({
    rag: true,
    memory: true,
    tools: false,
    web: true,
  });

  return (
    <main className="relative flex h-full min-w-0 flex-1 flex-col">
      {/* Top bar */}
      <header className="hairline-b relative z-10 flex h-14 shrink-0 items-center gap-3 px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-2 w-2 rounded-full bg-success shadow-glow-sm animate-pulse-glow" />
          <h1 className="font-display text-[15px] font-medium tracking-tight text-foreground">
            Refactor retrieval scoring
          </h1>
          <span className="rounded-md border border-border bg-secondary/40 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            context · 18.2k
          </span>
        </div>

        <div className="ml-auto flex items-center gap-1">
          <ModelPill />
          <button className="rounded-lg p-2 text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground">
            <Star className="h-4 w-4" strokeWidth={1.75} />
          </button>
          <button className="rounded-lg p-2 text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground">
            <Share2 className="h-4 w-4" strokeWidth={1.75} />
          </button>
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
          {/* Intelligence toggle — waveform */}
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
            <span
              className={[
                "ml-1 h-1.5 w-1.5 rounded-full transition",
                intelligenceOpen ? "bg-primary shadow-glow-sm animate-pulse-glow" : "bg-success animate-blink",
              ].join(" ")}
            />
          </button>
        </div>
      </header>

      {/* Conversation scroll */}
      <div className="relative flex-1 overflow-y-auto">
        {/* Ambient backdrop */}
        <div
          className="pointer-events-none absolute inset-0 bg-aurora opacity-70 animate-ambient"
          aria-hidden
        />
        <div className="relative mx-auto w-full max-w-[760px] px-8 pb-48 pt-10">
          <UserMessage>
            We're seeing degraded recall on long-tail queries in production. Can you analyze the
            current retrieval scoring and propose a hybrid approach that respects our latency
            budget (under 180ms p95)?
          </UserMessage>

          <AssistantMessage />

          <SourceCard />

          <InsightCard />
        </div>
      </div>

      {/* Floating prompt bar */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 px-8 pb-6">
        <div className="pointer-events-auto mx-auto w-full max-w-[760px]">
          <div className="relative">
            {/* Glow */}
            <div
              className="pointer-events-none absolute -inset-px rounded-[20px] bg-gradient-primary opacity-30 blur-2xl"
              aria-hidden
            />
            <div className="relative rounded-[20px] border border-border-strong bg-surface-elevated/90 shadow-panel backdrop-blur-xl">
              {/* Tool chips */}
              <div className="flex flex-wrap items-center gap-1.5 border-b border-border/60 px-4 py-2.5">
                <ToolChip
                  icon={<Database className="h-3 w-3" />}
                  label="RAG"
                  active={tools.rag}
                  onClick={() => setTools((t) => ({ ...t, rag: !t.rag }))}
                />
                <ToolChip
                  icon={<Brain className="h-3 w-3" />}
                  label="Memory"
                  active={tools.memory}
                  onClick={() => setTools((t) => ({ ...t, memory: !t.memory }))}
                />
                <ToolChip
                  icon={<Wrench className="h-3 w-3" />}
                  label="Tools"
                  active={tools.tools}
                  onClick={() => setTools((t) => ({ ...t, tools: !t.tools }))}
                />
                <ToolChip
                  icon={<Globe className="h-3 w-3" />}
                  label="Web"
                  active={tools.web}
                  onClick={() => setTools((t) => ({ ...t, web: !t.web }))}
                />
                <div className="ml-auto flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
                  <span className="h-1.5 w-1.5 rounded-full bg-success animate-blink" />
                  <span>connected · 14ms</span>
                </div>
              </div>

              {/* Textarea */}
              <div className="flex items-end gap-2 px-4 py-3">
                <button className="rounded-lg p-2 text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground">
                  <Paperclip className="h-4 w-4" strokeWidth={1.75} />
                </button>
                <textarea
                  rows={1}
                  placeholder="Ask ARBOR-AI anything — context, code, knowledge…"
                  className="flex-1 resize-none bg-transparent py-2 text-[14px] leading-6 text-foreground placeholder:text-muted-foreground focus:outline-none"
                />
                <button className="rounded-lg p-2 text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground">
                  <Mic className="h-4 w-4" strokeWidth={1.75} />
                </button>
                <button className="group relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-primary text-primary-foreground shadow-glow-sm transition hover:scale-105 hover:shadow-glow active:scale-95">
                  <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
                </button>
              </div>
            </div>

            <div className="mt-2.5 flex items-center justify-center gap-3 text-[10px] text-muted-foreground/70">
              <span>ARBOR-AI may surface inferred context.</span>
              <span className="h-1 w-1 rounded-full bg-muted-foreground/40" />
              <span className="font-mono">⏎ to send · ⇧⏎ for newline</span>
            </div>
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
      <span className="font-medium">ARBOR · Atlas-4</span>
      <ChevronDown className="h-3 w-3 text-muted-foreground" />
    </button>
  );
}

function ToolChip({
  icon,
  label,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={[
        "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition",
        active
          ? "border-primary/40 bg-gradient-accent-soft text-primary shadow-glow-sm"
          : "border-border bg-secondary/40 text-muted-foreground hover:text-foreground",
      ].join(" ")}
    >
      {icon}
      {label}
    </button>
  );
}

function UserMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-10 flex justify-end animate-fade-up">
      <div className="max-w-[85%] rounded-2xl rounded-tr-md border border-border bg-secondary/50 px-4 py-3 text-[14px] leading-7 text-foreground">
        {children}
      </div>
    </div>
  );
}

function AssistantMessage() {
  return (
    <div className="mb-8 flex gap-4 animate-fade-up">
      <div className="relative mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-primary shadow-glow-sm">
        <Sparkles className="h-3.5 w-3.5 text-primary-foreground" strokeWidth={2.5} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-2 flex items-center gap-2">
          <span className="text-[12px] font-medium text-foreground">Atlas-4</span>
          <span className="rounded-md bg-secondary/60 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
            reasoning · 4 steps
          </span>
          <span className="text-[10px] text-muted-foreground">· 1.2s</span>
        </div>

        <div className="space-y-4 text-[14.5px] leading-7 text-foreground/90">
          <p>
            Your current scorer relies on cosine similarity over a single dense embedding space,
            which collapses on entity-heavy queries. I traced 84 production failures and found
            three recurring patterns:
          </p>

          <ul className="space-y-2 pl-1">
            {[
              {
                title: "Lexical mismatch",
                detail: "Long-tail product codes never embed close to natural-language queries.",
              },
              {
                title: "Recency bias absent",
                detail: "Stale documents outrank recent revisions of the same source.",
              },
              {
                title: "Section granularity",
                detail: "Whole-document chunks dilute relevance signal at retrieval time.",
              },
            ].map((item, i) => (
              <li key={i} className="flex gap-3">
                <span className="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                <div>
                  <span className="font-medium text-foreground">{item.title}.</span>{" "}
                  <span className="text-muted-foreground">{item.detail}</span>
                </div>
              </li>
            ))}
          </ul>

          <p>
            I'd recommend a <span className="text-gradient-primary font-medium">hybrid scorer</span>{" "}
            combining BM25 lexical recall, dense semantic similarity, and a lightweight reranker —
            all behind a 180ms latency budget.
          </p>

          {/* Code block */}
          <div className="overflow-hidden rounded-xl border border-border bg-card/60">
            <div className="flex items-center justify-between border-b border-border/60 px-3.5 py-2">
              <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
                <Code2 className="h-3 w-3" />
                retrieval/scorer.ts
              </div>
              <button className="rounded-md p-1 text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground">
                <Copy className="h-3 w-3" />
              </button>
            </div>
            <pre className="overflow-x-auto px-4 py-3 font-mono text-[12px] leading-6 text-foreground/85">
{`const score = (
  0.45 * bm25(query, doc)
  + 0.40 * cosine(embed(query), doc.vector)
  + 0.15 * rerank(query, doc.snippet)
);
return docs.sort(byScore).slice(0, k);`}
            </pre>
          </div>
        </div>

        {/* Action row */}
        <div className="mt-4 flex items-center gap-1">
          {[
            { icon: Copy, label: "Copy" },
            { icon: RotateCcw, label: "Regenerate" },
            { icon: ThumbsUp, label: "Helpful" },
            { icon: ThumbsDown, label: "Not helpful" },
          ].map(({ icon: Icon, label }) => (
            <button
              key={label}
              className="rounded-md p-1.5 text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground"
              aria-label={label}
            >
              <Icon className="h-3.5 w-3.5" strokeWidth={1.75} />
            </button>
          ))}
          <span className="ml-2 font-mono text-[10px] text-muted-foreground/70">
            812 tokens · $0.0042
          </span>
        </div>
      </div>
    </div>
  );
}

function SourceCard() {
  const [open, setOpen] = useState(true);
  const sources = [
    { title: "retrieval/scorer.ts", type: "code", snippet: "Current scorer implementation" },
    { title: "RAG eval — Q3 traces", type: "doc", snippet: "84 failure cases analyzed" },
    { title: "internal/ranking-rfc.md", type: "doc", snippet: "Hybrid ranking proposal" },
    { title: "datadog · p95 latency", type: "metric", snippet: "180ms threshold dashboard" },
  ];

  return (
    <div className="mb-8 ml-11">
      <button
        onClick={() => setOpen((o) => !o)}
        className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground transition hover:text-foreground"
      >
        <ChevronDown
          className={`h-3 w-3 transition ${open ? "" : "-rotate-90"}`}
        />
        4 sources cited
      </button>
      {open && (
        <div className="grid grid-cols-2 gap-2">
          {sources.map((s) => (
            <a
              key={s.title}
              className="group flex items-start gap-2.5 rounded-xl border border-border bg-card/40 p-3 transition hover:border-border-strong hover:bg-card/70"
            >
              <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-secondary/70">
                <FileText className="h-3.5 w-3.5 text-primary" strokeWidth={1.75} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1">
                  <span className="truncate font-mono text-[11px] text-foreground">
                    {s.title}
                  </span>
                  <ExternalLink className="h-2.5 w-2.5 shrink-0 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
                </div>
                <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                  {s.snippet}
                </div>
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function InsightCard() {
  return (
    <div className="ml-11 animate-fade-up">
      <div className="relative overflow-hidden rounded-2xl border border-border bg-gradient-accent-soft p-5">
        <div
          className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-primary/15 blur-3xl"
          aria-hidden
        />
        <div className="relative">
          <div className="mb-2 flex items-center gap-2">
            <Brain className="h-3.5 w-3.5 text-primary" />
            <span className="text-[11px] font-medium uppercase tracking-wider text-primary">
              Contextual insight
            </span>
          </div>
          <h3 className="font-display text-[16px] font-medium text-foreground">
            This pattern matches 3 prior threads in your workspace
          </h3>
          <p className="mt-1.5 text-[13px] leading-6 text-muted-foreground">
            Last quarter's <span className="text-foreground">"Embedding drift analysis"</span> reached
            a similar conclusion. Memory suggests starting from that scorer rather than
            greenfield.
          </p>

          <div className="mt-4 flex items-center gap-3 border-t border-border/60 pt-3 font-mono text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-primary" /> confidence 0.92
            </span>
            <span className="h-3 w-px bg-border" />
            <span>3 related threads</span>
            <span className="h-3 w-px bg-border" />
            <span>generated locally</span>
          </div>
        </div>
      </div>
    </div>
  );
}
