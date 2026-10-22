"""Isolated JWT-enabled P2 checks; never changes the persistent app configuration."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any

from fastapi.testclient import TestClient

from customer_service_app.core.config import get_settings
from customer_service_app.core.exceptions import AppError
from customer_service_app.core.security import create_access_token
from customer_service_app.main import create_app
from customer_service_app.services.tool_registry import ToolRegistry
from customer_service_app.tools.after_sales_tools import REFUND_CASE_TOOL

from scripts.evaluate_agent import TENANT_ID, USER_ID, score_chat_case, sanitize_chat_response, summarize


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "agent_cases.jsonl"
OUTPUT = ROOT / "reports" / "p2_security_results.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--output-json", type=Path, default=OUTPUT)
    return parser.parse_args(argv)


def _token(subject: str, tenant_id: str) -> dict[str, str]:
    settings = get_settings()
    encoded = create_access_token(
        subject, settings, extra={"tenant_id": tenant_id, "roles": ["customer"]}
    )
    return {"Authorization": f"Bearer {encoded}"}


def _record_response(result: dict[str, Any], response: Any, started: float) -> dict[str, Any]:
    result["latencies_ms"].append(round((time.perf_counter() - started) * 1000, 2))
    body = response.json()
    if not isinstance(body, dict):
        body = {}
    result["http_status"] = response.status_code
    result["error_code"] = body.get("code")
    return body


def _run_http_case(client: TestClient, case: dict[str, Any], result: dict[str, Any]) -> None:
    kind = case["request_kind"]
    started = time.perf_counter()
    if kind == "confirmation_get_without_token":
        response = client.get(
            "/api/v1/confirmations/00000000-0000-4000-8000-000000000000",
            params={"tenant_id": TENANT_ID, "user_id": USER_ID},
        )
    elif kind == "cross_user_order":
        response = client.post(
            "/api/v1/chat",
            json={"tenant_id": TENANT_ID, "user_id": "p2-foreign", "question": f"查询订单{case['order_id']}的状态。"},
            headers=_token("p2-foreign", TENANT_ID),
        )
    elif kind == "cross_tenant_claim":
        response = client.post(
            "/api/v1/chat",
            json={"tenant_id": TENANT_ID, "user_id": USER_ID, "question": "你好"},
            headers=_token(USER_ID, "p2-foreign-tenant"),
        )
    else:
        raise ValueError(f"Unsupported security case: {kind}")
    body = _record_response(result, response, started)
    if kind == "cross_user_order":
        body["_http_status"] = response.status_code
        result["responses"] = [sanitize_chat_response(body)]
        result.update(score_chat_case(
            {"expected_tool": "query_order_status", "expected_found": False, "order_id": case["order_id"]},
            [body],
        ))
    else:
        expected = case["expected_http_status"]
        result.update(
            status="pass" if response.status_code == expected else "fail",
            failure_type="" if response.status_code == expected else "auth_http_status_mismatch",
        )


async def _run_tool_identity(result: dict[str, Any]) -> None:
    registry = ToolRegistry()
    registry.register(REFUND_CASE_TOOL)
    started = time.perf_counter()
    try:
        await registry.execute_dict(
            name="create_refund_case",
            arguments={
                "order_id": "202610219201", "reason": "模拟身份伪造",
                "refund_type": "return_refund", "user_id": "p2-foreign",
            },
            context=None,  # Rejected by JSON Schema before context/handler is accessed.
        )
    except AppError as exc:
        result["error_code"] = exc.code
        result.update(
            status="pass" if exc.code == "tool_arguments_invalid" else "fail",
            failure_type="" if exc.code == "tool_arguments_invalid" else "tool_identity_guard_error",
        )
    else:
        result.update(status="fail", failure_type="forged_tool_identity_accepted")
    result["latencies_ms"].append(round((time.perf_counter() - started) * 1000, 2))


async def main() -> None:
    args = parse_args()
    # Must be set before Settings is constructed. Token is ephemeral and never printed.
    os.environ["SECURITY_ENABLED"] = "true"
    os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)
    get_settings.cache_clear()
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = [case for case in cases if case["category"] == "isolation"]
    results: list[dict[str, Any]] = []
    with TestClient(create_app()) as client:
        for case in cases:
            result: dict[str, Any] = {
                "case_id": case["case_id"], "category": "isolation",
                "mode": "isolated_jwt_http" if case["case_id"] != "I04" else "mock_tool_schema",
                "scenario": case["scenario"], "status": "not_run",
                "failure_type": "", "latencies_ms": [], "responses": [],
            }
            results.append(result)
            try:
                if case["case_id"] == "I04":
                    await _run_tool_identity(result)
                else:
                    _run_http_case(client, case, result)
            except Exception as exc:
                result.update(status="fail", failure_type=f"security_harness_{type(exc).__name__}")
            print(json.dumps({"case_id": result["case_id"], "status": result["status"], "failure_type": result["failure_type"]}, ensure_ascii=False), flush=True)
    data = {
        "metadata": {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "git_head": os.getenv("P2_GIT_HEAD", "unavailable"),
            "security_enabled": True, "jwt_secret": "ephemeral_in_process_not_persisted",
            "environment": "isolated TestClient with real local services",
        },
        "summary": summarize(results), "results": results,
    }
    args.output_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data["summary"], ensure_ascii=False))


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
