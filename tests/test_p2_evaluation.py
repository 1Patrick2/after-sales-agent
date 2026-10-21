"""P2 evaluation contracts: fixed cases, honest denominators, and safe evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.evaluate_agent import (
    _git_head,
    RequestBudget,
    load_cases,
    percentile,
    sanitize_chat_response,
    score_chat_case,
    select_cases,
    summarize,
)


CASES = Path(__file__).resolve().parents[1] / "evals" / "agent_cases.jsonl"


def test_fixed_cases_have_expected_partition_and_unique_ids() -> None:
    cases = load_cases(CASES)
    assert len(cases) == 40
    assert len({case["case_id"] for case in cases}) == 40
    assert {category: sum(c["category"] == category for c in cases) for category in {
        "knowledge", "orders", "conversation", "refund", "isolation", "fault"
    }} == {
        "knowledge": 8, "orders": 8, "conversation": 6,
        "refund": 8, "isolation": 4, "fault": 6,
    }
    assert all(c.get("scenario") for c in cases)
    assert all(c.get("messages") or c.get("request_kind") for c in cases)
    assert all(c.get("expected_ticket_delta") in (0, 1) for c in cases if c["mode"] == "refund")


def test_case_selector_and_unknown_id() -> None:
    cases = load_cases(CASES)
    selected = select_cases(cases, case_ids=["O02", "K01"], categories=[], max_cases=None)
    assert [item["case_id"] for item in selected] == ["K01", "O02"]
    assert len(select_cases(cases, case_ids=[], categories=["refund"], max_cases=2)) == 2
    with pytest.raises(ValueError, match="Unknown case"):
        select_cases(cases, case_ids=["NOPE"], categories=[], max_cases=None)


def test_chat_scoring_requires_trace_not_answer_text() -> None:
    case = next(c for c in load_cases(CASES) if c["case_id"] == "O01")
    response = {
        "answer": "订单 202610219001 已发货",
        "status": "completed",
        "tool_calls": [],
        "tool_results": [],
    }
    verdict = score_chat_case(case, [response])
    assert verdict["status"] == "fail"
    assert verdict["failure_type"] == "tool_selection_error"


def test_knowledge_structural_success_still_needs_semantic_review() -> None:
    case = next(c for c in load_cases(CASES) if c["case_id"] == "K01")
    response = {
        "status": "completed",
        "knowledge": [{"source": case["expected_source"]}],
        "answer": "看起来正确，但不可自动证明忠实",
    }
    assert score_chat_case(case, [response])["status"] == "needs_review"


def test_intermediate_clarification_then_completed_tool_call_is_not_graph_failure() -> None:
    case = next(c for c in load_cases(CASES) if c["case_id"] == "C02")
    response = [
        {"status": "needs_clarification", "tool_calls": [], "tool_results": []},
        {
            "status": "completed",
            "tool_calls": [{"name": "query_logistics_status", "arguments": {"order_id": case["order_id"]}}],
            "tool_results": [{"name": "query_logistics_status", "ok": True, "payload": {"found": True}}],
        },
    ]
    assert score_chat_case(case, response)["status"] == "pass"


def test_no_order_clarification_is_not_automatically_a_failure() -> None:
    case = next(c for c in load_cases(CASES) if c["case_id"] == "C06")
    response = [{"status": "needs_clarification", "tool_results": []}] * 2
    assert score_chat_case(case, response)["status"] == "needs_review"


def test_sanitized_evidence_excludes_answers_and_payloads() -> None:
    secret = "sk-test-p2-secret"
    response = {
        "answer": secret,
        "run_id": "run-1",
        "thread_id": "thread-1",
        "status": "completed",
        "knowledge": [{"source": "faq/safe.md", "content": secret}],
        "tool_results": [{"name": "query_order_status", "payload": {"token": secret}}],
        "trace": [{"stage": "tools", "detail": secret, "metadata": {"key": secret}}],
    }
    sanitized = sanitize_chat_response(response)
    assert secret not in json.dumps(sanitized)
    assert sanitized["run_id"] == "run-1"
    assert sanitized["sources"] == ["faq/safe.md"]


def test_summary_keeps_failures_and_manual_reviews_in_denominator() -> None:
    results = [
        {"case_id": "A", "status": "pass", "latencies_ms": [100.0]},
        {"case_id": "B", "status": "fail", "failure_type": "timeout", "latencies_ms": [300.0]},
        {"case_id": "C", "status": "needs_review", "latencies_ms": [200.0]},
        {"case_id": "D", "status": "not_run", "latencies_ms": []},
    ]
    summary = summarize(results)
    assert summary["attempted"] == 3
    assert summary["pass"] == 1
    assert summary["fail"] == 1
    assert summary["needs_review"] == 1
    assert summary["not_run"] == 1
    assert summary["confirmed_success_rate"] == pytest.approx(1 / 3, abs=0.0001)
    assert summary["latency_ms"]["p50"] == 200.0
    assert summary["latency_ms"]["p95"] == 290.0
    assert percentile([], 95) is None


def test_duplicate_case_id_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.jsonl"
    path.write_text('\n'.join([
        json.dumps({"case_id": "X", "category": "knowledge", "mode": "chat", "scenario": "first", "messages": ["a"]}),
        json.dumps({"case_id": "X", "category": "knowledge", "mode": "chat", "scenario": "second", "messages": ["b"]}),
    ]), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        load_cases(path)


def test_git_metadata_falls_back_when_container_has_no_git(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_git(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr("scripts.evaluate_agent.subprocess.run", missing_git)
    monkeypatch.setenv("P2_GIT_HEAD", "35bbb13-test")
    assert _git_head() == "35bbb13-test"


def test_http_budget_is_a_hard_limit() -> None:
    budget = RequestBudget(1)
    budget.claim()
    assert budget.count == 1
    with pytest.raises(RuntimeError, match="http_request_budget_exhausted"):
        budget.claim()
    assert budget.count == 1
