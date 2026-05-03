# Phase 4: Concurrency Control & Benchmarking

## Overview

Phase 4 implements **turn-level concurrency control** to prevent resource exhaustion under high load, and provides a **benchmark harness** for load testing the entire system.

## Architecture

### Concurrency Limiter

The `TurnConcurrencyLimiter` uses a bounded semaphore to enforce a maximum number of concurrent turns across all sessions:

```
┌─ Session A (turn 1) ─┐
│   [acquire] → QUEUED  │  < Semaphore: max=4
├─ Session B (turn 1) ─┤
│   [acquire] → ACTIVE │  < Slot 1
├─ Session C (turn 2) ─┤
│   [acquire] → ACTIVE │  < Slot 2
├─ Session D (turn 1) ─┤
│   [acquire] → ACTIVE │  < Slot 3
├─ Session E (turn 1) ─┤
│   [acquire] → ACTIVE │  < Slot 4
└─ Session F (turn 1) ─┘
   [acquire] → BLOCKED    (waits for a slot to free)
```

### Components

#### 1. **TurnConcurrencyLimiter** (`backend/concurrency_limiter.py`)

```python
class TurnConcurrencyLimiter:
    async def acquire_turn(session_id: str) -> float:
        # Blocks if semaphore full, returns queue wait time in ms

    def release_turn() -> None:
        # Release one semaphore slot

    def get_metrics() -> ConcurrencyMetrics:
        # Snapshot of current state
```

**Metrics Tracked:**

- `max_concurrent_turns`: Configured limit
- `current_active_turns`: Currently executing
- `queued_sessions`: Waiting for slot
- `total_turns_processed`: Lifetime count
- `total_wait_ms`: Cumulative queue time

#### 2. **WebSocket Integration** (`backend/main.py`)

Each turn is wrapped:

```python
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket, session_id):
    limiter = app.state.turn_limiter

    # Text turns
    if msg_type == "text_input":
        wait_ms = await limiter.acquire_turn(session_id)
        try:
            breakdown = await manager.handle_text_turn(...)
            await websocket.send_json({
                "type": "turn_complete",
                "latency_breakdown": breakdown.get("stages", {}),
                "queue_wait_ms": wait_ms,  # NEW: Queue time
            })
        finally:
            limiter.release_turn()
```

#### 3. **Metrics Endpoint** (`GET /api/metrics/concurrency`)

```bash
curl http://localhost:8001/api/metrics/concurrency
```

Response:

```json
{
  "max_concurrent_turns": 4,
  "current_active_turns": 2,
  "queued_sessions": 1,
  "total_turns_processed": 156,
  "total_wait_ms": 245.8
}
```

## Configuration

### Settings

In `backend/config.py`:

```python
max_concurrent_turns: int = Field(
    default=4,
    alias="MAX_CONCURRENT_TURNS"
)
turn_queue_timeout_seconds: float = Field(
    default=5.0,
    alias="TURN_QUEUE_TIMEOUT_SECONDS"
)
```

### Environment

```bash
# .env or shell
export MAX_CONCURRENT_TURNS=8           # Allow 8 concurrent turns
export TURN_QUEUE_TIMEOUT_SECONDS=10.0  # Wait up to 10s for a slot
```

## Benchmarking

### Benchmark Script

`scripts/benchmark_concurrent.py` spawns N concurrent sessions sending M turns each:

```bash
# Run with defaults (8 sessions × 2 turns)
python scripts/benchmark_concurrent.py

# Custom load test
python scripts/benchmark_concurrent.py \
    --url http://localhost:8001 \
    --sessions 16 \
    --turns 5

# 80 total turns against the backend
```

### Output

```
======================================================================
CONCURRENCY BENCHMARK
======================================================================
Backend URL:           http://localhost:8001
Concurrent sessions:   8
Turns per session:     2
Total turns:           16
Start time:            2024-XX-XX...
======================================================================

[1/3] Creating 8 sessions...
  ✓ Session 1/8
  ✓ Session 2/8
  ...

[2/3] Running 16 concurrent turns...

[3/3] Collecting metrics...

RESULTS
----------------------------------------------------------------------
Total turns:           16
Successful:            16
Errors:                0
Timeouts:              0

LATENCY (ms)
----------------------------------------------------------------------
Min latency:           450.23
Max latency:           2134.56
Mean latency:          890.45
Median latency:        850.12
Mean queue wait:       125.34
Max queue wait:        450.78

THROUGHPUT
----------------------------------------------------------------------
Total time:            18.34s
Throughput:            0.87 turns/sec

CONCURRENCY LIMITER STATE
----------------------------------------------------------------------
Max concurrent turns:  4
Current active turns:  0
Queued sessions:       0
Total turns processed: 16
Total queue wait:      2005.44ms
```

## Usage Scenarios

### 1. **Load Testing** - Verify System Saturation Point

```bash
# Find where system starts queueing
python scripts/benchmark_concurrent.py --sessions 8 --turns 3   # 24 turns
python scripts/benchmark_concurrent.py --sessions 16 --turns 3  # 48 turns
python scripts/benchmark_concurrent.py --sessions 32 --turns 2  # 64 turns
```

**Analysis:**

- Monitor queue_wait_ms increases
- Watch total throughput plateau
- Identify when limiter reaches max_concurrent_turns

### 2. **Tuning max_concurrent_turns** - Optimize for Your Hardware

```bash
# Conservative (2 slots) - low latency, lower throughput
MAX_CONCURRENT_TURNS=2 python scripts/benchmark_concurrent.py --sessions 4 --turns 5

# Aggressive (16 slots) - higher throughput, higher latency
MAX_CONCURRENT_TURNS=16 python scripts/benchmark_concurrent.py --sessions 4 --turns 5

# Find your sweet spot based on:
# - Available CPU cores
# - GPU memory (if using accelerators)
# - LLM model inference speed
# - Acceptable queue wait times
```

### 3. **Production Simulation** - Realistic Traffic Patterns

```bash
# Simulate 100 users making 10 queries each (1000 total turns)
python scripts/benchmark_concurrent.py --sessions 100 --turns 10
```

## Lifecycle

### Acquisition Flow

1. Client sends `{"type": "text_input", "message": "..."}`
2. WebSocket handler calls `limiter.acquire_turn(session_id)`
   - If semaphore has capacity: proceed immediately (0ms wait)
   - If semaphore full: wait in queue (potentially 100s of ms)
   - If queue times out: raise `RuntimeError` → send error to client
3. Handler processes turn (domain check, LLM inference, tools, etc.)
4. Handler calls `limiter.release_turn()` in finally block
5. Next queued session's turn can now proceed

### Example Timeline (4 concurrent max)

```
t=0ms   [Session A] acquire (wait=0ms) → SLOT 1
        [Session B] acquire (wait=0ms) → SLOT 2
        [Session C] acquire (wait=0ms) → SLOT 3
        [Session D] acquire (wait=0ms) → SLOT 4
        [Session E] acquire (wait=50ms, QUEUED)
        [Session F] acquire (wait=50ms, QUEUED)

t=500ms [Session A] turn complete, release
        [Session E] now acquires SLOT 1 (wait=500ms)

t=750ms [Session B] turn complete, release
        [Session F] now acquires SLOT 2 (wait=750ms)

t=1200ms [Session E] turn complete
         [Session F] turn complete
```

## Testing

### Unit Tests

```bash
pytest tests/test_concurrency_limiter.py -v
```

Tests cover:

- Basic acquire/release
- Blocking when semaphore full
- FIFO fairness
- Timeout handling
- Concurrent load
- Metrics tracking

### Manual Testing

```python
import asyncio
from backend.concurrency_limiter import TurnConcurrencyLimiter

async def test():
    limiter = TurnConcurrencyLimiter(max_concurrent=2)

    # Acquire two slots
    w1 = await limiter.acquire_turn("s1")
    w2 = await limiter.acquire_turn("s2")
    print(f"Acquired: {w1:.2f}ms, {w2:.2f}ms")

    # Release
    limiter.release_turn()
    limiter.release_turn()

    metrics = limiter.get_metrics()
    print(f"Metrics: active={metrics.current_active_turns}, total={metrics.total_turns_processed}")

asyncio.run(test())
```

## Monitoring in Production

### Health Check Queries

```bash
# Check current limiter state
curl http://localhost:8001/api/metrics/concurrency | jq .

# Monitor over time
watch -n 1 'curl -s http://localhost:8001/api/metrics/concurrency | jq .'

# Parse specific metrics
curl -s http://localhost:8001/api/metrics/concurrency | jq '.current_active_turns'
```

### Alert Thresholds

```
WARNING if:
  - current_active_turns = max_concurrent_turns for >30 seconds
  - queued_sessions > 5
  - total_wait_ms grows linearly

CRITICAL if:
  - queue_timeout_seconds exceeded frequently
  - throughput drops below 0.5 turns/sec
```

## Tuning Guide

### For Latency-Sensitive Workloads

```bash
# Use lower concurrency limit
MAX_CONCURRENT_TURNS=2
TURN_QUEUE_TIMEOUT_SECONDS=3.0

# Result: Predictable response times, less queueing
```

### For Throughput-Optimized Workloads

```bash
# Use higher concurrency limit (but watch resource usage)
MAX_CONCURRENT_TURNS=16
TURN_QUEUE_TIMEOUT_SECONDS=30.0

# Result: Higher queries/sec, potential for longer queues
```

### For Balanced Workloads

```bash
# Default (recommended for most setups)
MAX_CONCURRENT_TURNS=4
TURN_QUEUE_TIMEOUT_SECONDS=5.0

# Result: Good balance of throughput and responsiveness
```

## Troubleshooting

### High Queue Wait Times

**Symptom:** `queue_wait_ms` in turn responses increasing

**Causes:**

1. Too many concurrent sessions
2. Individual turns taking too long (slow LLM inference)
3. Bottleneck in tool execution (CRM/stock price calls)

**Solutions:**

- Increase `MAX_CONCURRENT_TURNS` if CPU/GPU available
- Profile turn execution with latency tracker
- Optimize slow external tool calls (add caching/timeouts)

### Turn Queue Timeouts

**Symptom:** Frequent `RuntimeError: Turn queue timeout` errors

**Causes:**

1. `TURN_QUEUE_TIMEOUT_SECONDS` too short for current load
2. Backend overloaded, turns not progressing
3. Resource leak causing memory pressure

**Solutions:**

- Increase `TURN_QUEUE_TIMEOUT_SECONDS` temporarily
- Monitor system resources (CPU, memory, disk)
- Reduce `MAX_CONCURRENT_TURNS` if resources constrained
- Restart backend if suspected resource leak

### Uneven Load Distribution

**Symptom:** Some sessions get faster responses, others slow

**Expected:** Varies with natural request timing + semaphore fairness (FIFO)

**Solutions:**

- Run multiple load tests to average
- Monitor `/api/metrics/concurrency` for steady state
- Use benchmark script with more turns for statistical significance

## Integration with Phase 1-3

| Phase | Feature             | Integration                                         |
| ----- | ------------------- | --------------------------------------------------- |
| 1     | Session Persistence | Each session can be queued independently            |
| 2     | Domain Restriction  | Domain check happens after acquiring turn slot      |
| 3     | Summarization       | Summary injection happens after acquiring turn slot |
| **4** | **Concurrency**     | **Limiter gates all turn entry points**             |

## Performance Expectations

### Baseline (Single Turn)

- LLM inference: 500-1500ms
- Domain classifier: 10-50ms
- RAG retrieval: 100-300ms
- Tool execution: 100-500ms
- **Total: 700-2350ms per turn**

### With Concurrency (N=4 max)

- Sequential turns: 2800-9400ms
- Concurrent (ideal): 700-2350ms (4 in parallel)
- With queuing: 1400-3500ms (depending on arrival pattern)

### Benchmark Results (Expected)

```
--sessions 4 --turns 4 (16 turns total)
  - Throughput: ~0.6-0.8 turns/sec
  - Queue wait: 0-500ms (depending on concurrency max)

--sessions 8 --turns 5 (40 turns total)
  - Throughput: ~0.4-0.6 turns/sec
  - Queue wait: 100-1000ms

--sessions 16 --turns 10 (160 turns total)
  - Throughput: ~0.2-0.4 turns/sec
  - Queue wait: 500-2000ms (approaching timeout)
```

## Summary

Phase 4 delivers:

1. **Concurrency Control** - Bounded semaphore preventing resource exhaustion
2. **Queue Management** - FIFO fairness with configurable timeouts
3. **Metrics & Observability** - Endpoint and response instrumentation
4. **Benchmarking** - Load test harness for validation
5. **Configurability** - Easy tuning for different workloads

The system can now safely handle multiple concurrent users with predictable resource usage and clear visibility into queue behavior.
