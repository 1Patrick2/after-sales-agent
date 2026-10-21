"""Persisted P2 trace evidence must exclude arbitrary tool payload content."""

import json

from scripts.collect_p2_trace_evidence import sanitize_run


def test_trace_sanitizer_keeps_found_and_drops_secret_payload() -> None:
    secret = "sk-test-never-persist"
    raw = {
        "id": "run-1", "model": "test-model", "steps": [{
            "name": "execute_tool_call", "status": "success", "latency_ms": 2.0,
            "input": {"authorization": secret},
            "output": {"tool_name": "query_order_status", "ok": True,
                       "payload": {"found": False, "order_id": "202610219001", "token": secret}},
        }],
    }
    safe = sanitize_run(raw)
    assert safe["steps"][0]["found"] is False
    assert safe["steps"][0]["order_id"] == "202610219001"
    assert secret not in json.dumps(safe)


def test_trace_sanitizer_keeps_bounded_retrieval_route_only() -> None:
    raw = {
        "id": "run-2", "steps": [{
            "name": "retrieve", "status": "success",
            "input": {"question": "sensitive"},
            "output": {"route": {"source": "realtime_tool", "reason": "complex_dependency_requires_planner",
                                  "document_types": [], "execution_mode": "planner"},
                       "chunk_count": 0, "raw_answer": "sensitive"},
        }],
    }
    safe = sanitize_run(raw)
    assert safe["steps"][0]["retrieval_route"]["source"] == "realtime_tool"
    assert "sensitive" not in json.dumps(safe)
