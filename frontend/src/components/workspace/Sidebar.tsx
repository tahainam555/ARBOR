import { useState } from "react";
import {
  Plus,
  Search,
  Pin,
  MessageSquare,
  Sparkles,
  Database,
  Settings,
  ChevronDown,
  Layers,
  Folder,
  Command,
} from "lucide-react";

const pinned = [
  { id: 1, title: "Context engine architecture", time: "Active" },
  { id: 2, title: "RAG eval — production traces", time: "2h" },
];

const groups = [
  {
    label: "Today",
    items: [
      { id: 10, title: "Refactor retrieval scoring", active: true },
      { id: 11, title: "Embedding drift analysis" },
      { id: 12, title: "Prompt regression: claims agent" },
    ],
  },
  {
    label: "Yesterday",
    items: [
      { id: 20, title: "Memory compression heuristics" },
      { id: 21, title: "Tool routing benchmarks" },
      { id: 22, title: "Webhook latency triage" },
    ],
  },
  {
    label: "Last 7 days",
    items: [
      { id: 30, title: "Onboarding doc rewrite" },
      { id: 31, title: "Postgres → pgvector migration" },
      { id: 32, title: "Token throughput report" },
    ],
  },
];

export function Sidebar() {
  const [activeId, setActiveId] = useState<number>(10);

  return (
    <aside className="hairline-r relative flex h-full w-[268px] shrink-0 flex-col bg-sidebar/80">
      {/* Brand */}
      <div className="flex h-14 items-center gap-2.5 px-5">
        <div className="relative">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-primary shadow-glow-sm">
            <Layers className="h-3.5 w-3.5 text-primary-foreground" strokeWidth={2.5} />
          </div>
        </div>
        <div className="flex flex-1 items-center gap-1.5">
          <span className="font-display text-[15px] font-semibold tracking-tight text-foreground">
            ARBOR-AI
          </span>
          <span className="rounded-md bg-secondary/80 px-1.5 py-0.5 font-mono text-[9px] font-medium uppercase tracking-wider text-muted-foreground">
            v2.4
          </span>
        </div>
        <button className="rounded-md p-1.5 text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground">
          <ChevronDown className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* New chat */}
      <div className="px-3 pb-2 pt-1">
        <button className="group relative flex w-full items-center gap-2 overflow-hidden rounded-lg bg-gradient-primary px-3 py-2.5 text-sm font-medium text-primary-foreground shadow-glow-sm transition hover:shadow-glow">
          <Plus className="h-4 w-4" strokeWidth={2.5} />
          <span>New conversation</span>
          <span className="ml-auto flex items-center gap-0.5 rounded-md bg-black/15 px-1.5 py-0.5 font-mono text-[10px]">
            <Command className="h-2.5 w-2.5" /> N
          </span>
        </button>
      </div>

      {/* Search */}
      <div className="px-3 pb-3">
        <div className="group relative flex items-center gap-2 rounded-lg border border-border bg-input/40 px-3 py-2 transition focus-within:border-primary/50 focus-within:bg-input/70">
          <Search className="h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search threads, memory…"
            className="flex-1 bg-transparent text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none"
          />
          <span className="font-mono text-[10px] text-muted-foreground/70">⌘K</span>
        </div>
      </div>

      {/* Scrollable lists */}
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {/* Pinned */}
        <SectionLabel icon={<Pin className="h-3 w-3" />}>Pinned</SectionLabel>
        <ul className="mb-3 space-y-0.5">
          {pinned.map((item) => (
            <li key={item.id}>
              <button
                onClick={() => setActiveId(item.id)}
                className={navItemClass(activeId === item.id)}
              >
                <span className="flex h-1.5 w-1.5 shrink-0 rounded-full bg-primary shadow-glow-sm" />
                <span className="truncate">{item.title}</span>
                <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                  {item.time}
                </span>
              </button>
            </li>
          ))}
        </ul>

        {groups.map((group) => (
          <div key={group.label} className="mb-3">
            <SectionLabel>{group.label}</SectionLabel>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const isActive = activeId === item.id;
                return (
                  <li key={item.id}>
                    <button
                      onClick={() => setActiveId(item.id)}
                      className={navItemClass(isActive)}
                    >
                      <MessageSquare
                        className={`h-3.5 w-3.5 shrink-0 ${isActive ? "text-primary" : "text-muted-foreground/70"}`}
                        strokeWidth={1.75}
                      />
                      <span className="truncate">{item.title}</span>
                      {isActive && (
                        <span className="ml-auto h-1.5 w-1.5 rounded-full bg-primary shadow-glow-sm" />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      {/* Memory + footer */}
      <div className="hairline-t mt-auto px-3 py-3">
        <div className="rounded-xl border border-border bg-card/50 p-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Database className="h-3 w-3 text-primary" />
              <span className="text-[11px] font-medium text-foreground">Memory</span>
            </div>
            <span className="font-mono text-[10px] text-muted-foreground">62%</span>
          </div>
          <div className="relative h-1 overflow-hidden rounded-full bg-secondary/60">
            <div
              className="absolute inset-y-0 left-0 rounded-full bg-gradient-primary shadow-glow-sm"
              style={{ width: "62%" }}
            />
          </div>
          <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
            <span>12.4k vectors</span>
            <span className="font-mono">8 GB</span>
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <div className="relative h-7 w-7 rounded-full bg-gradient-primary p-px">
              <div className="flex h-full w-full items-center justify-center rounded-full bg-sidebar text-[11px] font-semibold text-foreground">
                E
              </div>
            </div>
            <div className="leading-tight">
              <div className="text-[12px] font-medium text-foreground">Eli Rodríguez</div>
              <div className="text-[10px] text-muted-foreground">Pro · workspace</div>
            </div>
          </div>
          <button className="rounded-md p-1.5 text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground">
            <Settings className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}

function SectionLabel({
  children,
  icon,
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-1.5 px-2.5 pb-1.5 pt-1 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground/70">
      {icon}
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
