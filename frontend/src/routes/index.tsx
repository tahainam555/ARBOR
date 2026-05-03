import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Sidebar } from "@/components/workspace/Sidebar";
import { Conversation } from "@/components/workspace/Conversation";
import { IntelligencePanel } from "@/components/workspace/IntelligencePanel";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "ARBOR-AI — AI Workspace" },
      {
        name: "description",
        content:
          "ARBOR-AI is the memory-aware AI workspace. Context engineering, retrieval, and observability for production-grade intelligence.",
      },
      { property: "og:title", content: "ARBOR-AI — AI Workspace" },
      {
        property: "og:description",
        content: "Context engineering, retrieval, and live observability in one calm interface.",
      },
    ],
  }),
  component: Workspace,
});

function Workspace() {
  const [panelOpen, setPanelOpen] = useState(false);

  return (
    <div className="relative flex h-screen w-full overflow-hidden bg-background text-foreground">
      {/* Global ambient backdrop */}
      <div
        className="pointer-events-none absolute inset-0 bg-aurora opacity-60"
        aria-hidden
      />
      {/* Subtle grain via radial mask */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.025] mix-blend-overlay"
        style={{
          backgroundImage:
            "radial-gradient(oklch(1 0 0 / 1) 1px, transparent 1px)",
          backgroundSize: "3px 3px",
        }}
        aria-hidden
      />

      <div className="relative z-10 flex h-full w-full">
        <Sidebar />
        <Conversation
          intelligenceOpen={panelOpen}
          onToggleIntelligence={() => setPanelOpen((o) => !o)}
        />
      </div>

      <IntelligencePanel open={panelOpen} onClose={() => setPanelOpen(false)} />
    </div>
  );
}
