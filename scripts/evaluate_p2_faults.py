"""Run two fixed P2 fault cases against existing Mock regression tests."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.evaluate_agent import summarize


ROOT = Path(__file__).resolve().parents[1]
TESTS = {
    "F05": "tests/test_p1_fault_boundaries.py::test_planner_model_failure_uses_bounded_rule_fallback_without_executing_tool",
    "F06": "tests/test_p1_fault_boundaries.py::test_tool_timeout_cancels_cooperative_handler_before_side_effect",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-json", type=Path, default=ROOT / "reports" / "p2_fault_results.json"
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    results = []
    for case_id, nodeid in TESTS.items():
        started = time.perf_counter()
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", nodeid],
            cwd=ROOT, capture_output=True, text=True, timeout=45, check=False,
        )
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        passed = completed.returncode == 0 and "1 passed" in completed.stdout
        result = {
            "case_id": case_id, "category": "fault", "mode": "mock_regression",
            "scenario": "LLM 失效时受控回退" if case_id == "F05" else "工具超时协作取消",
            "status": "pass" if passed else "fail",
            "failure_type": "" if passed else "mock_regression_failed",
            "latencies_ms": [elapsed], "pytest_nodeid": nodeid,
            "return_code": completed.returncode,
            "evidence": "one existing Mock test; not a real API fault injection",
        }
        results.append(result)
        print(json.dumps({"case_id": case_id, "status": result["status"]}, ensure_ascii=False), flush=True)
    data = {
        "metadata": {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "git_head": os.getenv("P2_GIT_HEAD", "unavailable"),
            "environment": "pytest Mock regression; no real LLM or HTTP fault",
        },
        "summary": summarize(results), "results": results,
    }
    args.output_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
