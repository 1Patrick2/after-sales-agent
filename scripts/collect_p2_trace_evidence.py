"""Read-only, redacted Agent Run trace evidence for fixed P2 case run IDs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
INPUTS = [
    ROOT / "reports" / "p2_agent_results.json",
    ROOT / "reports" / "p2_agent_rescore_results.json",
    ROOT / "reports" / "p2_security_results.json",
]
OUTPUT = ROOT / "reports" / "p2_trace_evidence.json"


def run_ids_from_results() -> list[str]:
    ids: set[str] = set()
    for path in INPUTS:
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["results"]:
            if row.get("run_id"):
                ids.add(row["run_id"])
            for response in row.get("responses", []):
                if response.get("run_id"):
                    ids.add(response["run_id"])
    return sorted(ids)


def sanitize_run(run: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for step in run.get("steps", []):
        output = step.get("output") or {}
        payload = output.get("payload") or {}
        item = {
            "name": step.get("name"), "status": step.get("status"),
            "latency_ms": step.get("latency_ms"),
        }
        if step.get("name") == "retrieve":
            route = output.get("route") or {}
            item["retrieval_route"] = {
                "source": route.get("source"),
                "reason": route.get("reason"),
                "document_types": route.get("document_types", []),
                "execution_mode": route.get("execution_mode"),
                "chunk_count": output.get("chunk_count"),
            }
        if output.get("tool_name"):
            item["tool_name"] = output.get("tool_name")
            item["tool_ok"] = output.get("ok") is True
            item["found"] = payload.get("found") if isinstance(payload.get("found"), bool) else None
            item["order_id"] = payload.get("order_id") if str(payload.get("order_id", "")).isdigit() else None
        steps.append(item)
    return {
        "run_id": run.get("id"), "status": run.get("status"),
        "model": run.get("model"), "total_tokens": run.get("total_tokens"),
        "error_code": run.get("error_code"), "steps": steps,
    }


async def main() -> None:
    result: dict[str, Any] = {}
    async with httpx.AsyncClient(base_url="http://app:8000", timeout=12.0) as client:
        for run_id in run_ids_from_results():
            try:
                response = await client.get(f"/api/v1/agent-runs/{run_id}")
                if response.status_code == 200:
                    result[run_id] = sanitize_run(response.json())
                else:
                    result[run_id] = {"http_status": response.status_code}
            except httpx.RequestError:
                result[run_id] = {"http_status": "request_error"}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "requested_runs": len(result),
        "retrieved": sum(item.get("run_id") is not None for item in result.values()),
        "tool_steps": sum(bool(step.get("tool_name")) for item in result.values() for step in item.get("steps", [])),
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
