"""Merged P2 report must keep all 40 fixed cases and separate Mock latency."""

from scripts.merge_p2_results import combine_results, latency_summary


def test_merge_replaces_gated_cases_and_preserves_denominator() -> None:
    cases = [
        {"case_id": "A", "category": "orders", "mode": "chat"},
        {"case_id": "B", "category": "isolation", "mode": "auth_live"},
        {"case_id": "C", "category": "fault", "mode": "mock_fault"},
    ]
    main = [
        {"case_id": "A", "status": "pass", "category": "orders", "mode": "chat", "latencies_ms": [10.0], "responses": [{}]},
        {"case_id": "B", "status": "not_run", "category": "isolation", "mode": "auth_live", "latencies_ms": []},
        {"case_id": "C", "status": "not_run", "category": "fault", "mode": "mock_fault", "latencies_ms": []},
    ]
    secure = [{"case_id": "B", "status": "pass", "category": "isolation", "mode": "isolated_jwt_http", "latencies_ms": [15.0]}]
    mock = [{"case_id": "C", "status": "fail", "category": "fault", "mode": "mock_regression", "latencies_ms": [30.0]}]
    merged = combine_results(cases, main, secure, mock)
    assert [row["case_id"] for row in merged] == ["A", "B", "C"]
    assert [row["status"] for row in merged] == ["pass", "pass", "fail"]
    assert latency_summary(merged)["real_network_chat"]["request_count"] == 1
    assert latency_summary(merged)["real_network_chat"]["p95"] == 10.0


def test_merge_rejects_duplicate_result() -> None:
    cases = [{"case_id": "A", "category": "orders", "mode": "chat"}]
    row = {"case_id": "A", "status": "pass", "category": "orders", "mode": "chat"}
    try:
        combine_results(cases, [row, row], [], [])
    except ValueError as exc:
        assert "Duplicate" in str(exc)
    else:
        raise AssertionError("duplicate result was accepted")


def test_merge_can_use_documented_rerun_without_losing_original_status() -> None:
    cases = [{"case_id": "A", "category": "conversation", "mode": "chat"}]
    old = {"case_id": "A", "status": "fail", "category": "conversation", "mode": "chat", "failure_type": "graph_status_error"}
    new = {"case_id": "A", "status": "needs_review", "category": "conversation", "mode": "chat", "failure_type": "manual_semantic_review_pending"}
    merged = combine_results(cases, [old], [], [], rerun=[new])
    assert merged[0]["status"] == "needs_review"
    assert merged[0]["previous_status"] == "fail"
