from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import httpx
import pytest
from scipy.spatial.distance import cosine

from evals._shared import DATA_DIR, fetch_json, read_json, similarity_model, websocket_turn
from evals.config import config

GT = read_json("rag_ground_truth.json")
SIM_MODEL = similarity_model()


@pytest.mark.asyncio
async def test_precision_at_k_overall() -> None:
    results = []
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        for item in GT["queries"]:
            resp = await client.get(
                "/api/rag/retrieve",
                params={"query": item["query"], "top_k": config.TOP_K},
            )
            resp.raise_for_status()
            chunks = resp.json()["chunks"]
            retrieved_ids = [chunk["id"] for chunk in chunks]
            relevant = set(item["relevant_chunk_ids"])
            hits = sum(1 for cid in retrieved_ids if cid in relevant)
            precision = hits / max(1, len(retrieved_ids))
            results.append({"id": item["id"], "precision": precision, "hits": hits})

    average = sum(item["precision"] for item in results) / len(results)
    payload = {"metric": "precision_at_k", "average": average, "threshold": config.PRECISION_AT_K_THRESHOLD, "passed": average >= config.PRECISION_AT_K_THRESHOLD, "per_query": results}
    (Path("report") / "rag_retrieval_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert average >= config.PRECISION_AT_K_THRESHOLD


@pytest.mark.asyncio
async def test_recall_at_k_overall() -> None:
    results = []
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        for item in GT["queries"]:
            resp = await client.get(
                "/api/rag/retrieve",
                params={"query": item["query"], "top_k": config.TOP_K},
            )
            resp.raise_for_status()
            chunks = resp.json()["chunks"]
            retrieved_ids = [chunk["id"] for chunk in chunks]
            relevant = set(item["relevant_chunk_ids"])
            hits = sum(1 for cid in retrieved_ids if cid in relevant)
            recall = hits / max(1, len(relevant))
            results.append({"id": item["id"], "recall": recall})

    average = sum(item["recall"] for item in results) / len(results)
    assert average >= 0.60


@pytest.mark.asyncio
async def test_ticker_filter_accuracy() -> None:
    company_queries = [item for item in GT["queries"] if len(item.get("relevant_tickers", [])) == 1]
    successes = 0
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        for item in company_queries[:10]:
            ticker = item["relevant_tickers"][0]
            resp = await client.get(
                "/api/rag/retrieve",
                params={"query": item["query"], "top_k": config.TOP_K, "filter_ticker": ticker},
            )
            resp.raise_for_status()
            chunks = resp.json()["chunks"]
            if chunks and all(chunk["metadata"]["ticker"] == ticker for chunk in chunks):
                successes += 1

    accuracy = successes / max(1, min(10, len(company_queries)))
    assert accuracy >= 0.90


@pytest.mark.asyncio
async def test_retrieval_latency() -> None:
    samples = GT["queries"][:11]
    latencies = []
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        for item in samples:
            start = time.perf_counter()
            resp = await client.get(
                "/api/rag/retrieve",
                params={"query": item["query"], "top_k": config.TOP_K},
            )
            resp.raise_for_status()
            latencies.append((time.perf_counter() - start) * 1000.0)

    warm_latencies = latencies[1:]
    assert sum(warm_latencies) / len(warm_latencies) < 2000


@pytest.mark.asyncio
async def test_faithfulness_and_answer_correctness() -> None:
    faithfulness_scores = []
    correctness_scores = []
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=120.0) as client:
        for item in GT["queries"][:10]:
            answer, _, _, _ = await websocket_turn(f"eval_rag_{item['id']}", item["query"])
            rag_resp = await client.get("/api/rag/retrieve", params={"query": item["query"], "top_k": config.TOP_K})
            rag_resp.raise_for_status()
            chunks = rag_resp.json()["chunks"]
            contexts = "\n".join(chunk["text"] for chunk in chunks)

            answer_embedding = SIM_MODEL.encode(answer)
            gt_embedding = SIM_MODEL.encode(item["expected_answer"])
            similarity = 1 - cosine(answer_embedding, gt_embedding)
            correctness_scores.append(similarity)

            source_bonus = 1.0 if "Sources:" in answer else 0.0
            context_embedding = SIM_MODEL.encode(contexts)
            context_similarity = 1 - cosine(answer_embedding, context_embedding)
            faithfulness_scores.append((max(0.0, context_similarity) + source_bonus) / 2.0)

    assert statistics.mean(faithfulness_scores) >= config.FAITHFULNESS_THRESHOLD
    assert statistics.mean(correctness_scores) >= config.ANSWER_CORRECTNESS_THRESHOLD
