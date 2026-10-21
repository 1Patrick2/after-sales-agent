"""Fixed P2 Agent evaluation. Default mode only validates cases; --live sends HTTP.

Run inside the existing app image with /app/src, /app/scripts, /app/evals and
/app/reports mounted. Never place credentials or raw model responses in reports.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import random
import subprocess
import time
from typing import Any

import httpx
from sqlalchemy import select

from customer_service_app.core.config import get_settings
from customer_service_app.infrastructure.db.models import Order, SupportTicket
from customer_service_app.infrastructure.db.session import dispose_engine, session_context


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "agent_cases.jsonl"
DEFAULT_RESULTS = ROOT / "reports" / "p2_agent_results.json"
DEFAULT_REPORT = ROOT / "reports" / "p2_agent_evaluation_2026-10-21.md"
CATEGORIES = {"knowledge", "orders", "conversation", "refund", "isolation", "fault"}
MODES = {"chat", "refund", "http_negative", "auth_live", "mock_fault"}
TENANT_ID = "p2-evaluation"
USER_ID = "p2-customer"
ATTEMPTED = {"pass", "fail", "needs_review"}


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load an immutable-at-run-time JSONL case set with basic schema checks."""
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"Missing case_id at line {line_number}")
        if case_id in seen:
            raise ValueError(f"Duplicate case_id: {case_id}")
        if case.get("category") not in CATEGORIES or case.get("mode") not in MODES:
            raise ValueError(f"Invalid category or mode: {case_id}")
        if not case.get("scenario") or not (case.get("messages") or case.get("request_kind")):
            raise ValueError(f"Missing scenario/input: {case_id}")
        if case["mode"] == "refund" and case.get("expected_ticket_delta") not in (0, 1):
            raise ValueError(f"Missing refund delta: {case_id}")
        seen.add(case_id)
        cases.append(case)
    return cases


def select_cases(
    cases: list[dict[str, Any]], *, case_ids: list[str], categories: list[str],
    max_cases: int | None,
) -> list[dict[str, Any]]:
    known = {case["case_id"] for case in cases}
    unknown = set(case_ids) - known
    if unknown:
        raise ValueError(f"Unknown case: {', '.join(sorted(unknown))}")
    unknown_categories = set(categories) - CATEGORIES
    if unknown_categories:
        raise ValueError(f"Unknown category: {', '.join(sorted(unknown_categories))}")
    selected = [
        case for case in cases
        if (not case_ids or case["case_id"] in case_ids)
        and (not categories or case["category"] in categories)
    ]
    return selected[:max_cases] if max_cases is not None else selected


def percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolated percentile; document sample size with each result."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * p / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 2)


def sanitize_chat_response(response: dict[str, Any]) -> dict[str, Any]:
    """Persist only evidence fields; drop answer, tool arguments/payload and free-form trace."""
    return {
        "http_status": response.get("_http_status"),
        "status": response.get("status"),
        "run_id": response.get("run_id"),
        "thread_id": response.get("thread_id"),
        "conversation_id": response.get("conversation_id"),
        "confirmation_id": (response.get("pending_confirmation") or {}).get("id"),
        "tool_calls": [str(item.get("name", "")) for item in response.get("tool_calls", [])],
        "tool_results": [
            {"name": str(item.get("name", "")), "ok": item.get("ok") is True}
            for item in response.get("tool_results", [])
        ],
        "sources": [str(item.get("source", "")) for item in response.get("knowledge", [])],
        "trace_stages": [str(item.get("stage", "")) for item in response.get("trace", [])],
    }


def _found_value(payload: dict[str, Any]) -> bool | None:
    if isinstance(payload.get("found"), bool):
        return payload["found"]
    for key in ("result", "data"):
        nested = payload.get(key)
        if isinstance(nested, dict) and isinstance(nested.get("found"), bool):
            return nested["found"]
    return None


def score_chat_case(case: dict[str, Any], responses: list[dict[str, Any]]) -> dict[str, str]:
    """Deterministic, evidence-only checks. Semantic correctness is never auto-passed."""
    if not responses or any(response.get("_http_status", 200) != 200 for response in responses):
        return {"status": "fail", "failure_type": "http_error"}
    allowed_statuses = {"completed", "needs_clarification", None}
    if any(response.get("status") not in allowed_statuses for response in responses):
        return {"status": "fail", "failure_type": "graph_status_error"}
    if responses[-1].get("status") not in ({"completed", "needs_clarification"} if case.get("expected_no_found_order") else {"completed", None}):
        return {"status": "fail", "failure_type": "graph_status_error"}
    tool_results = [item for response in responses for item in response.get("tool_results", [])]
    tool_calls = [item for response in responses for item in response.get("tool_calls", [])]
    expected_tool = case.get("expected_tool")
    if expected_tool and not any(item.get("name") == expected_tool and item.get("ok") is True for item in tool_results):
        return {"status": "fail", "failure_type": "tool_selection_error"}
    if case.get("order_id") and expected_tool:
        target = str(case["order_id"])
        matched = [item for item in tool_calls if item.get("name") == expected_tool]
        if not any(str(item.get("arguments", {}).get("order_id")) == target for item in matched):
            return {"status": "fail", "failure_type": "tool_parameter_error"}
    if "expected_found" in case:
        matching = [item for item in tool_results if item.get("name") == expected_tool]
        values = [_found_value(item.get("payload") or {}) for item in matching]
        if case["expected_found"] not in values:
            return {"status": "fail", "failure_type": "business_result_error"}
    if case.get("expected_no_found_order"):
        if any(_found_value(item.get("payload") or {}) is True for item in tool_results):
            return {"status": "fail", "failure_type": "hallucinated_order"}
    if case.get("expected_source"):
        sources = [item.get("source") for response in responses for item in response.get("knowledge", [])]
        if case["expected_source"] not in sources:
            return {"status": "fail", "failure_type": "retrieval_miss"}
    if case.get("semantic_review"):
        return {"status": "needs_review", "failure_type": "manual_semantic_review_pending"}
    return {"status": "pass", "failure_type": ""}


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(result["status"] for result in results)
    attempted = sum(statuses[status] for status in ATTEMPTED)
    latencies = [float(value) for result in results for value in result.get("latencies_ms", [])]
    failures = Counter(result.get("failure_type", "unspecified") for result in results if result["status"] == "fail")
    return {
        "total_selected": len(results),
        "attempted": attempted,
        "pass": statuses["pass"],
        "fail": statuses["fail"],
        "needs_review": statuses["needs_review"],
        "not_run": statuses["not_run"],
        "confirmed_success_rate": round(statuses["pass"] / attempted, 4) if attempted else None,
        "failure_types": dict(sorted(failures.items())),
        "latency_ms": {
            "request_count": len(latencies),
            "mean": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
        },
    }


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return os.getenv("P2_GIT_HEAD", "unavailable")
    return result.stdout.strip() if result.returncode == 0 else os.getenv("P2_GIT_HEAD", "unavailable")


class RequestBudget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.count = 0

    def claim(self) -> None:
        if self.count >= self.limit:
            raise RuntimeError("http_request_budget_exhausted")
        self.count += 1


async def _request(
    client: httpx.AsyncClient, budget: RequestBudget, method: str, url: str,
    *, json_body: dict[str, Any] | None = None, params: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any], float]:
    budget.claim()
    started = time.perf_counter()
    response = await client.request(method, url, json=json_body, params=params)
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}, elapsed


async def _ticket_count(order_id: str) -> int:
    async with session_context() as session:
        tickets = (
            await session.execute(select(SupportTicket).where(
                SupportTicket.tenant_id == TENANT_ID,
                SupportTicket.user_id == USER_ID,
                SupportTicket.category == "refund",
            ))
        ).scalars().all()
    return sum((ticket.metadata_json or {}).get("order_id") == order_id for ticket in tickets)


async def seed_orders(cases: list[dict[str, Any]]) -> dict[str, int]:
    """Only insert P2 synthetic orders after global ID collision checks."""
    order_ids = sorted({case["order_id"] for case in cases if case.get("order_id") and case["category"] not in {"isolation", "fault"}})
    created = 0
    async with session_context() as session:
        for order_id in order_ids:
            existing = (await session.execute(select(Order).where(Order.order_id == order_id))).scalar_one_or_none()
            if existing and (existing.tenant_id != TENANT_ID or existing.user_id != USER_ID or (existing.metadata_json or {}).get("fixture") != "p2_evaluation"):
                raise ValueError(f"Order ID collision; no new orders written: {order_id}")
        for order_id in order_ids:
            existing = (await session.execute(select(Order).where(Order.order_id == order_id))).scalar_one_or_none()
            if existing is None:
                session.add(Order(
                    tenant_id=TENANT_ID, user_id=USER_ID, order_id=order_id,
                    status="shipped", logistics_company="模拟物流",
                    tracking_number=f"P2{order_id}",
                    metadata_json={"fixture": "p2_evaluation", "product": "模拟售后商品", "amount": 199},
                ))
                created += 1
        await session.commit()
    return {"expected": len(order_ids), "created": created, "existing_owned": len(order_ids) - created}


async def _verify_seed_order(order_id: str) -> None:
    async with session_context() as session:
        order = (await session.execute(select(Order).where(Order.order_id == order_id))).scalar_one_or_none()
    if order is None or order.tenant_id != TENANT_ID or order.user_id != USER_ID or (order.metadata_json or {}).get("fixture") != "p2_evaluation":
        raise ValueError(f"Missing/foreign P2 fixture: {order_id}")


async def _chat_messages(
    case: dict[str, Any], client: httpx.AsyncClient, budget: RequestBudget,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    conversation_id: str | None = None
    thread_id: str | None = None
    for question in case["messages"]:
        payload: dict[str, Any] = {"tenant_id": TENANT_ID, "user_id": USER_ID, "question": question}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if thread_id:
            payload["thread_id"] = thread_id
        code, body, latency = await _request(client, budget, "POST", "/api/v1/chat", json_body=payload)
        body["_http_status"] = code
        result["latencies_ms"].append(latency)
        result["responses"].append(sanitize_chat_response(body))
        responses.append(body)
        if code != 200:
            break
        conversation_id = body.get("conversation_id") or conversation_id
        thread_id = body.get("thread_id") or thread_id
    return responses


async def _run_chat(case: dict[str, Any], client: httpx.AsyncClient, budget: RequestBudget, result: dict[str, Any]) -> None:
    if case.get("order_id") and case.get("expected_found") is True:
        await _verify_seed_order(case["order_id"])
    before = await _ticket_count(case["order_id"]) if case.get("order_id") else None
    responses = await _chat_messages(case, client, budget, result)
    verdict = score_chat_case(case, responses)
    result.update(verdict)
    if before is not None:
        after = await _ticket_count(case["order_id"])
        result["refund_tickets_before"] = before
        result["refund_tickets_after"] = after
        if "expected_ticket_delta" in case and after - before != case["expected_ticket_delta"]:
            result.update(status="fail", failure_type="unexpected_database_write")


async def _run_refund(case: dict[str, Any], client: httpx.AsyncClient, budget: RequestBudget, result: dict[str, Any]) -> None:
    order_id = case["order_id"]
    await _verify_seed_order(order_id)
    before = await _ticket_count(order_id)
    result["refund_tickets_before"] = before
    if before != 0:
        result.update(status="not_run", failure_type="fixture_already_has_refund_ticket")
        return
    responses = await _chat_messages(case, client, budget, result)
    if not responses or responses[-1].get("_http_status") != 200:
        result.update(status="fail", failure_type="http_error")
        return
    pending = responses[-1].get("pending_confirmation") or {}
    confirmation_id = pending.get("id")
    thread_id = responses[-1].get("thread_id")
    result["confirmation_id"] = confirmation_id
    result["thread_id"] = thread_id
    result["run_id"] = responses[-1].get("run_id")
    if not confirmation_id or pending.get("status") != "pending" or not thread_id:
        result.update(status="fail", failure_type="confirmation_not_created")
        return
    pre_decision_count = await _ticket_count(order_id)
    result["refund_tickets_pending"] = pre_decision_count
    if pre_decision_count != 0:
        result.update(status="fail", failure_type="premature_database_write")
        return
    graph_code, graph, latency = await _request(client, budget, "GET", f"/api/v1/graph/threads/{thread_id}")
    result["latencies_ms"].append(latency)
    result["checkpoint"] = {
        "http_status": graph_code, "status": graph.get("status"),
        "next_nodes": graph.get("next_nodes", []),
        "task_names": [item.get("name") for item in graph.get("tasks", [])],
    }
    if graph_code != 200 or not graph.get("tasks"):
        result.update(status="fail", failure_type="checkpoint_not_interrupt")
        return
    params = {"tenant_id": TENANT_ID, "user_id": USER_ID}
    confirmation_code, confirmation, latency = await _request(client, budget, "GET", f"/api/v1/confirmations/{confirmation_id}", params=params)
    result["latencies_ms"].append(latency)
    if confirmation_code != 200 or confirmation.get("status") != "pending":
        result.update(status="fail", failure_type="confirmation_state_error")
        return
    decision = case["decision"]
    body = {"tenant_id": TENANT_ID, "user_id": USER_ID}
    code, decided, latency = await _request(client, budget, "POST", f"/api/v1/confirmations/{confirmation_id}/{decision}", json_body=body)
    result["latencies_ms"].append(latency)
    result["decision_http_status"] = code
    result["decision_status"] = decided.get("status")
    result["decision_trace_stages"] = [item.get("stage") for item in decided.get("trace", [])]
    after = await _ticket_count(order_id)
    result["refund_tickets_after"] = after
    expected_status = "executed" if decision == "approve" else "rejected"
    if code != 200 or decided.get("status") != expected_status or after - before != case["expected_ticket_delta"]:
        result.update(status="fail", failure_type="confirmation_or_database_mismatch")
        return
    if case.get("repeat_decision"):
        repeat_code, _, repeat_latency = await _request(client, budget, "POST", f"/api/v1/confirmations/{confirmation_id}/{decision}", json_body=body)
        result["latencies_ms"].append(repeat_latency)
        result["repeat_decision_http_status"] = repeat_code
        repeat_count = await _ticket_count(order_id)
        result["refund_tickets_after_repeat"] = repeat_count
        if repeat_code != 409 or repeat_count != after:
            result.update(status="fail", failure_type="duplicate_confirmation_write")
            return
    result.update(status="pass", failure_type="")


async def _run_http_negative(case: dict[str, Any], client: httpx.AsyncClient, budget: RequestBudget, result: dict[str, Any]) -> None:
    kind = case["request_kind"]
    if kind == "empty_question":
        method, url, body, params = "POST", "/api/v1/chat", {"tenant_id": TENANT_ID, "user_id": USER_ID, "question": ""}, None
    elif kind == "missing_user":
        method, url, body, params = "POST", "/api/v1/chat", {"tenant_id": TENANT_ID, "question": "你好"}, None
    elif kind == "missing_confirmation":
        method, url, body, params = "GET", "/api/v1/confirmations/00000000-0000-4000-8000-000000000000", None, {"tenant_id": TENANT_ID, "user_id": USER_ID}
    else:
        raise ValueError(f"Unsupported negative case: {kind}")
    code, response, latency = await _request(client, budget, method, url, json_body=body, params=params)
    result["latencies_ms"].append(latency)
    result["http_status"] = code
    result["error_code"] = response.get("code")
    result.update(status="pass" if code == case["expected_http_status"] else "fail", failure_type="" if code == case["expected_http_status"] else "http_status_mismatch")


async def run_live(
    cases: list[dict[str, Any]], *, base_url: str, timeout_seconds: float,
    max_http_requests: int, seed: int,
) -> dict[str, Any]:
    random.seed(seed)
    settings = get_settings()
    budget = RequestBudget(max_http_requests)
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout_seconds) as client:
        for case in cases:
            result: dict[str, Any] = {
                "case_id": case["case_id"], "category": case["category"], "mode": case["mode"],
                "scenario": case["scenario"], "status": "not_run", "failure_type": "",
                "latencies_ms": [], "responses": [],
            }
            results.append(result)
            if case["mode"] in {"auth_live", "mock_fault"}:
                result["failure_type"] = "requires_isolated_security_or_mock_harness"
                continue
            try:
                if case["mode"] == "refund":
                    await _run_refund(case, client, budget, result)
                elif case["mode"] == "http_negative":
                    await _run_http_negative(case, client, budget, result)
                else:
                    await _run_chat(case, client, budget, result)
            except httpx.TimeoutException:
                result.update(status="fail", failure_type="timeout")
            except httpx.RequestError:
                result.update(status="fail", failure_type="http_transport_error")
            except RuntimeError as exc:
                if str(exc) == "http_request_budget_exhausted":
                    result.update(
                        status="fail" if result["latencies_ms"] else "not_run",
                        failure_type="http_request_budget_exhausted",
                    )
                    break
                result.update(status="fail", failure_type="runtime_error")
            except Exception as exc:
                result.update(status="fail", failure_type=f"runner_error_{type(exc).__name__}")
            print(json.dumps({"case_id": result["case_id"], "status": result["status"], "failure_type": result["failure_type"]}, ensure_ascii=False), flush=True)
    for case in cases[len(results):]:
        results.append({"case_id": case["case_id"], "category": case["category"], "mode": case["mode"], "scenario": case["scenario"], "status": "not_run", "failure_type": "http_request_budget_exhausted", "latencies_ms": [], "responses": []})
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(), "seed": seed, "model": settings.llm_model,
        "embedding_provider": settings.embedding_provider,
        "retrieval_mode_configured": settings.retrieval_mode,
        "opensearch_enabled": settings.opensearch_enabled,
        "security_enabled": settings.security_enabled,
        "graph_checkpointer": settings.graph_checkpointer,
        "base_url": base_url, "concurrency": 1, "timeout_seconds": timeout_seconds,
        "max_http_requests": max_http_requests, "actual_http_requests": budget.count,
        "note": "HTTP count is not upstream LLM call count; SDK/graph may retry.",
    }
    return {"metadata": metadata, "summary": summarize(results), "results": results}


def render_markdown(data: dict[str, Any]) -> str:
    summary = data["summary"]
    lines = [
        "# P2 Agent 端到端评测（2026-10-21）", "",
        "## 范围和分母", "",
        f"固定选中 {summary['total_selected']} 例；已尝试 {summary['attempted']}，确认通过 {summary['pass']}，失败 {summary['fail']}，待人工语义复核 {summary['needs_review']}，未执行 {summary['not_run']}。",
        f"保守确认成功率：{summary['confirmed_success_rate']}（通过数 / 已尝试数；待复核也保留在分母）。", "",
        "未执行案例不进入已尝试分母；失败、超时和待复核不得静默剔除。回复文本正确但无工具/DB 证据不判成功。", "",
        "## 环境", "",
        f"Git `{data['metadata']['git_head']}`；模型 `{data['metadata']['model']}`；配置检索模式 `{data['metadata']['retrieval_mode_configured']}`；OpenSearch `{data['metadata']['opensearch_enabled']}`；串行 HTTP 请求 {data['metadata']['actual_http_requests']}。上游 LLM 调用次数和中转站费用未由此推断。", "",
        "## 逐例", "",
        "| Case | 类别 | 状态 | 失败/待检原因 | 请求数 |", "|---|---|---|---|---:|",
    ]
    for result in data["results"]:
        lines.append(f"| {result['case_id']} | {result['category']} | {result['status']} | {result.get('failure_type') or '—'} | {len(result.get('latencies_ms', []))} |")
    lines.extend(["", "## 失效分类", "", f"`{json.dumps(summary['failure_types'], ensure_ascii=False)}`", "", "## 局限", "", "知识问答的语义正确性与依据忠实性需人工复核；安全用例必须在独立开启 JWT 的环境执行；Mock 故障不能冒充真实服务故障。当前结果不是生产 SLA。", ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--seed-orders", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--base-url", default="http://app:8000")
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--max-http-requests", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    cases = select_cases(load_cases(args.cases), case_ids=args.case_id, categories=args.category, max_cases=args.max_cases)
    if args.seed_orders:
        print(json.dumps(await seed_orders(load_cases(args.cases)), ensure_ascii=False))
    if args.validate or not args.live:
        print(json.dumps({"validated_cases": len(cases), "categories": dict(Counter(case["category"] for case in cases))}, ensure_ascii=False))
        return
    if args.max_http_requests < 1 or args.timeout_seconds <= 0:
        raise ValueError("Positive request budget and timeout are required")
    data = await run_live(cases, base_url=args.base_url, timeout_seconds=args.timeout_seconds, max_http_requests=args.max_http_requests, seed=args.seed)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_md.write_text(render_markdown(data), encoding="utf-8")
    print(json.dumps(data["summary"], ensure_ascii=False))


async def main() -> None:
    try:
        await _main()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
