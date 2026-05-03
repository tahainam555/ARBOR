# SEC Investment Research Assistant Evaluation Report

Generated: {{generated_at}}

## Summary

{{summary_table}}

## Latency

{{latency_table}}

## Notes

- RAG retrieval is evaluated against annotated chunk IDs.
- Voice evaluation assumes generated audio samples exist in `evals/data/audio_samples`.
- Conversation quality uses Claude when `ANTHROPIC_API_KEY` is set, otherwise a deterministic fallback judge.
