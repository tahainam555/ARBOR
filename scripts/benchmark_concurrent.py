"""Benchmark concurrent turn execution and measure throughput/latency under load."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from datetime import datetime
from typing import Any

import aiohttp


async def create_session(base_url: str, session_http: aiohttp.ClientSession) -> str:
    """Create a new conversation session."""
    url = f"{base_url}/api/sessions"
    payload = {"session_id": str(uuid.uuid4()), "title": f"Benchmark-{uuid.uuid4().hex[:8]}"}
    async with session_http.post(url, json=payload) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Failed to create session: {resp.status}")
        data = await resp.json()
        return data["session_id"]


async def send_text_turn(
    base_url: str,
    session_id: str,
    message: str,
    session_http: aiohttp.ClientSession,
) -> dict[str, Any]:
    """Send a text turn via websocket and measure latency."""
    ws_url = f"{base_url.replace('http://', 'ws://').replace('https://', 'wss://')}/ws/{session_id}"
    turn_start = time.perf_counter()

    try:
        async with session_http.ws_connect(ws_url, heartbeat=None) as ws:
            await ws.send_json({"type": "text_input", "message": message})

            # Wait for response
            msg = await asyncio.wait_for(ws.receive_json(), timeout=30.0)
            turn_end = time.perf_counter()

            if msg.get("type") == "error":
                return {
                    "session_id": session_id,
                    "status": "error",
                    "message": msg.get("message"),
                    "latency_ms": (turn_end - turn_start) * 1000.0,
                }

            return {
                "session_id": session_id,
                "status": "success",
                "turn_id": msg.get("turn_id"),
                "latency_ms": (turn_end - turn_start) * 1000.0,
                "queue_wait_ms": msg.get("queue_wait_ms", 0.0),
            }
    except asyncio.TimeoutError:
        turn_end = time.perf_counter()
        return {
            "session_id": session_id,
            "status": "timeout",
            "latency_ms": (turn_end - turn_start) * 1000.0,
        }
    except Exception as exc:  # noqa: BLE001
        turn_end = time.perf_counter()
        return {
            "session_id": session_id,
            "status": "exception",
            "error": str(exc),
            "latency_ms": (turn_end - turn_start) * 1000.0,
        }


async def run_benchmark(
    base_url: str = "http://localhost:8001",
    num_concurrent_sessions: int = 8,
    turns_per_session: int = 2,
) -> None:
    """Run concurrent benchmark with N sessions × M turns each."""
    print(f"\n{'='*70}")
    print(f"CONCURRENCY BENCHMARK")
    print(f"{'='*70}")
    print(f"Backend URL:           {base_url}")
    print(f"Concurrent sessions:   {num_concurrent_sessions}")
    print(f"Turns per session:     {turns_per_session}")
    print(f"Total turns:           {num_concurrent_sessions * turns_per_session}")
    print(f"Start time:            {datetime.now().isoformat()}")
    print(f"{'='*70}\n")

    async with aiohttp.ClientSession() as session_http:
        # Create sessions
        print(f"[1/3] Creating {num_concurrent_sessions} sessions...")
        session_ids = []
        for i in range(num_concurrent_sessions):
            try:
                sid = await create_session(base_url, session_http)
                session_ids.append(sid)
                print(f"  ✓ Session {i+1}/{num_concurrent_sessions}")
            except Exception as exc:  # noqa: BLE001
                print(f"  ✗ Session {i+1} failed: {exc}")
                sys.exit(1)

        print(f"\n[2/3] Running {num_concurrent_sessions * turns_per_session} concurrent turns...")
        benchmark_start = time.perf_counter()

        # Create all tasks
        tasks = []
        for i, session_id in enumerate(session_ids):
            for turn_num in range(turns_per_session):
                task = send_text_turn(
                    base_url=base_url,
                    session_id=session_id,
                    message=f"What is the stock price of AAPL? (Session {i+1}, Turn {turn_num+1})",
                    session_http=session_http,
                )
                tasks.append(task)

        # Execute concurrently
        results = await asyncio.gather(*tasks, return_exceptions=False)
        benchmark_end = time.perf_counter()

        # Collect metrics
        print(f"\n[3/3] Collecting metrics...\n")

        successful = [r for r in results if r.get("status") == "success"]
        errors = [r for r in results if r.get("status") in ("error", "exception")]
        timeouts = [r for r in results if r.get("status") == "timeout"]

        latencies = [r["latency_ms"] for r in successful]
        queue_waits = [r.get("queue_wait_ms", 0.0) for r in successful if r.get("queue_wait_ms")]

        print(f"RESULTS")
        print(f"{'-'*70}")
        print(f"Total turns:           {len(results)}")
        print(f"Successful:            {len(successful)}")
        print(f"Errors:                {len(errors)}")
        print(f"Timeouts:              {len(timeouts)}")
        print()
        print(f"LATENCY (ms)")
        print(f"{'-'*70}")
        if latencies:
            print(f"Min latency:           {min(latencies):.2f}")
            print(f"Max latency:           {max(latencies):.2f}")
            print(f"Mean latency:          {sum(latencies)/len(latencies):.2f}")
            print(f"Median latency:        {sorted(latencies)[len(latencies)//2]:.2f}")
        if queue_waits:
            print(f"Mean queue wait:       {sum(queue_waits)/len(queue_waits):.2f}")
            print(f"Max queue wait:        {max(queue_waits):.2f}")
        print()
        print(f"THROUGHPUT")
        print(f"{'-'*70}")
        total_seconds = benchmark_end - benchmark_start
        throughput = len(successful) / total_seconds if total_seconds > 0 else 0.0
        print(f"Total time:            {total_seconds:.2f}s")
        print(f"Throughput:            {throughput:.2f} turns/sec")
        print()

        # Fetch backend metrics
        try:
            async with session_http.get(f"{base_url}/api/metrics/concurrency") as resp:
                if resp.status == 200:
                    metrics = await resp.json()
                    print(f"CONCURRENCY LIMITER STATE")
                    print(f"{'-'*70}")
                    print(f"Max concurrent turns:  {metrics['max_concurrent_turns']}")
                    print(f"Current active turns:  {metrics['current_active_turns']}")
                    print(f"Queued sessions:       {metrics['queued_sessions']}")
                    print(f"Total turns processed: {metrics['total_turns_processed']}")
                    print(f"Total queue wait:      {metrics['total_wait_ms']:.2f}ms")
        except Exception as exc:  # noqa: BLE001
            print(f"Could not fetch backend metrics: {exc}")

        print(f"\n{'='*70}\n")

        # Return summary
        return {
            "total_turns": len(results),
            "successful": len(successful),
            "errors": len(errors),
            "timeouts": len(timeouts),
            "min_latency_ms": min(latencies) if latencies else None,
            "max_latency_ms": max(latencies) if latencies else None,
            "mean_latency_ms": sum(latencies) / len(latencies) if latencies else None,
            "throughput_turns_per_sec": throughput,
            "total_time_seconds": total_seconds,
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Benchmark concurrent turn execution")
    parser.add_argument(
        "--url",
        default="http://localhost:8001",
        help="Backend URL (default: http://localhost:8001)",
    )
    parser.add_argument(
        "--sessions",
        type=int,
        default=8,
        help="Number of concurrent sessions (default: 8)",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=2,
        help="Turns per session (default: 2)",
    )

    args = parser.parse_args()

    try:
        asyncio.run(
            run_benchmark(
                base_url=args.url,
                num_concurrent_sessions=args.sessions,
                turns_per_session=args.turns,
            )
        )
    except KeyboardInterrupt:
        print("\nBenchmark interrupted")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"Benchmark failed: {exc}")
        sys.exit(1)
