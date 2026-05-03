from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from evals.config import config
from evals.report.plots import plot_concurrency_curve, plot_latency_comparison


RESULT_FILES = {
    "rag_retrieval": "report/rag_retrieval_results.json",
    "entity_extraction": "report/entity_extraction_results.json",
    "tool_invocation": "report/tool_invocation_results.json",
    "conversation_quality": "report/conversation_quality_results.json",
    "voice_stt": "report/voice_stt_results.json",
    "latency_simple": "report/latency_simple_dialogue.json",
    "latency_rag": "report/latency_rag_only.json",
    "latency_tool": "report/latency_tool_only.json",
    "latency_mixed": "report/latency_mixed.json",
    "concurrency": "report/concurrency_results.json",
}


def generate_report() -> dict:
    report_dir = Path("report")
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "plots").mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system": "SEC Investment Research Voice Assistant",
        "results": {},
    }

    for key, relative_path in RESULT_FILES.items():
        path = Path(relative_path)
        if path.exists():
            report["results"][key] = json.loads(path.read_text(encoding="utf-8"))

    plot_latency_comparison(report["results"])
    if "concurrency" in report["results"]:
        plot_concurrency_curve(report["results"]["concurrency"])

    markdown = _generate_markdown(report)
    (report_dir / "eval_report.md").write_text(markdown, encoding="utf-8")
    (report_dir / "eval_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _safe_get(results: dict, path: str, default=None):
    value = results
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return default
    return value


def _generate_markdown(report: dict) -> str:
    results = report["results"]
    return f"""# SEC Investment Research Assistant Evaluation Report

Generated: {report['generated_at']}

## Summary

| Component | Metric | Value | Threshold | Status |
|---|---:|---:|---:|---|
| RAG Retrieval | Precision@{config.TOP_K} | {_safe_get(results, 'rag_retrieval.average', 0):.3f} | {config.PRECISION_AT_K_THRESHOLD:.2f} | {'PASS' if _safe_get(results, 'rag_retrieval.passed', False) else 'FAIL'} |
| Entity Extraction | Accuracy | {_safe_get(results, 'entity_extraction.accuracy', 0):.3f} | {config.ENTITY_EXTRACTION_ACCURACY_THRESHOLD:.2f} | {'PASS' if _safe_get(results, 'entity_extraction.accuracy', 0) >= config.ENTITY_EXTRACTION_ACCURACY_THRESHOLD else 'FAIL'} |
| Tool Invocation | Accuracy | {_safe_get(results, 'tool_invocation.invocation_accuracy', 0):.3f} | {config.TOOL_INVOCATION_ACCURACY_THRESHOLD:.2f} | {'PASS' if _safe_get(results, 'tool_invocation.invocation_accuracy', 0) >= config.TOOL_INVOCATION_ACCURACY_THRESHOLD else 'FAIL'} |
| Conversation Quality | Avg Score | {_safe_get(results, 'conversation_quality.average_overall_score', 0):.2f}/5 | 3.50/5 | {'PASS' if _safe_get(results, 'conversation_quality.average_overall_score', 0) >= 3.5 else 'FAIL'} |
| STT Voice | WER | {_safe_get(results, 'voice_stt.average_wer', 0):.3f} | < {config.STT_WER_THRESHOLD:.2f} | {'PASS' if _safe_get(results, 'voice_stt.average_wer', 1) < config.STT_WER_THRESHOLD else 'FAIL'} |

## Latency

| Scenario | TTFT Median | E2E Median |
|---|---:|---:|
| Simple | {_safe_get(results, 'latency_simple.ttft.median', 0):.0f}ms | {_safe_get(results, 'latency_simple.e2e.median', 0):.0f}ms |
| RAG only | {_safe_get(results, 'latency_rag.ttft.median', 0):.0f}ms | {_safe_get(results, 'latency_rag.e2e.median', 0):.0f}ms |
| Tool only | {_safe_get(results, 'latency_tool.ttft.median', 0):.0f}ms | {_safe_get(results, 'latency_tool.e2e.median', 0):.0f}ms |
| Mixed | {_safe_get(results, 'latency_mixed.ttft.median', 0):.0f}ms | {_safe_get(results, 'latency_mixed.e2e.median', 0):.0f}ms |

## Charts

![Latency Comparison](plots/latency_comparison.png)
![Concurrency Curve](plots/concurrency_curve.png)
"""
