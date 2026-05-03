from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover - optional dependency guard
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    matplotlib = None
    plt = None


def plot_latency_comparison(results: dict) -> None:
    if plt is None:
        return

    labels = ["Simple", "RAG", "Tool", "Mixed"]
    keys = ["latency_simple", "latency_rag", "latency_tool", "latency_mixed"]
    ttft = [results.get(key, {}).get("ttft", {}).get("median", 0) for key in keys]
    e2e = [results.get(key, {}).get("e2e", {}).get("median", 0) for key in keys]

    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar([i - 0.2 for i in x], ttft, width=0.4, label="TTFT median")
    ax.bar([i + 0.2 for i in x], e2e, width=0.4, label="E2E median")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("ms")
    ax.set_title("Latency comparison")
    ax.legend()
    ax.grid(axis="y", alpha=0.2)

    Path("report/plots").mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig("report/plots/latency_comparison.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_concurrency_curve(results: dict) -> None:
    if plt is None:
        return

    per_level = results.get("per_level", [])
    levels = [item.get("n_users", 0) for item in per_level]
    ttft = [item.get("ttft", {}).get("median", 0) for item in per_level]
    e2e = [item.get("e2e", {}).get("median", 0) for item in per_level]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(levels, ttft, marker="o", label="TTFT median")
    ax.plot(levels, e2e, marker="s", label="E2E median")
    ax.set_xlabel("Concurrent users")
    ax.set_ylabel("ms")
    ax.set_title("Concurrency curve")
    ax.legend()
    ax.grid(alpha=0.2)

    Path("report/plots").mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig("report/plots/concurrency_curve.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
