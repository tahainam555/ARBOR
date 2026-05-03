# Evaluation Suite

## Run

```bash
pip install -r evals/requirements_eval.txt
python -m uvicorn backend.main:app --port 8000
python -m evals.run_evals
```

## Components

- `rag`: retrieval relevance, faithfulness, answer correctness
- `tools`: functional tool checks and invocation accuracy
- `memory`: entity extraction, within-session memory, CRM persistence
- `voice`: STT WER/latency, TTS output, first audio latency
- `conversation`: multi-turn judge scoring
- `latency`: scenario latency distribution
- `concurrency`: async load test
- `negative`: error handling and out-of-scope behavior

## Hardware Notes

Record CPU, RAM, OS, and whether the model runs on CPU or GPU before comparing runs.
