# SEC Investment Research Assistant Evaluation Report

Generated: 2026-05-03T21:20:01.237361+00:00

## Summary

| Component | Metric | Value | Threshold | Status |
|---|---:|---:|---:|---|
| RAG Retrieval | Precision@5 | 0.000 | 0.70 | FAIL |
| Entity Extraction | Accuracy | 0.000 | 0.90 | FAIL |
| Tool Invocation | Accuracy | 0.000 | 0.85 | FAIL |
| Conversation Quality | Avg Score | 0.00/5 | 3.50/5 | FAIL |
| STT Voice | WER | 0.000 | < 0.10 | FAIL |

## Latency

| Scenario | TTFT Median | E2E Median |
|---|---:|---:|
| Simple | 0ms | 0ms |
| RAG only | 0ms | 0ms |
| Tool only | 0ms | 0ms |
| Mixed | 0ms | 0ms |

## Charts

![Latency Comparison](plots/latency_comparison.png)
![Concurrency Curve](plots/concurrency_curve.png)
