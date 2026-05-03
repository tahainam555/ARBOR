from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from evals.report.generator import generate_report


COMPONENT_MAP = {
    "rag": "evals/test_rag.py",
    "tools": "evals/test_tools.py",
    "memory": "evals/test_memory.py",
    "voice": "evals/test_voice.py",
    "conversation": "evals/test_conversation.py",
    "latency": "evals/test_latency.py",
    "negative": "evals/test_negative.py",
}


def run_pytest(test_file: str) -> bool:
    result = subprocess.run([sys.executable, "-m", "pytest", test_file, "-q"], check=False)
    return result.returncode == 0


async def run_concurrency_test() -> dict:
    from evals.test_concurrency import run_full_load_test

    return await run_full_load_test()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SEC evaluation suite")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--component", type=str, default=None)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    Path("report").mkdir(exist_ok=True)

    if args.report_only:
        generate_report()
        return

    if args.component:
        components = {args.component: COMPONENT_MAP[args.component]}
    elif args.quick:
        components = {k: v for k, v in COMPONENT_MAP.items() if k not in {"latency", "conversation"}}
    else:
        components = COMPONENT_MAP

    results: dict[str, str] = {}
    print("=" * 60)
    print("SEC Investment Assistant - Evaluation Suite")
    print("=" * 60)

    for name, path in components.items():
        print(f"Running {name}...")
        results[name] = "PASS" if run_pytest(path) else "FAIL"
        print(f"  -> {results[name]}")

    if not args.quick and (args.component is None or args.component == "concurrency"):
        print("Running concurrency load test...")
        asyncio.run(run_concurrency_test())
        results["concurrency"] = "COMPLETE"

    generate_report()
    print("=" * 60)
    for name, status in results.items():
        print(f"{name}: {status}")
    print("Report: report/eval_report.md")
    print("=" * 60)


if __name__ == "__main__":
    main()
