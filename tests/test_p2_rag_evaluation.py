"""Cleaned Dense RAG benchmark keeps expired/non-knowledge cases out of recall denominator."""

from pathlib import Path

from scripts.evaluate_p2_rag import compute_retrieval_metrics, load_rag_cases


CASES = Path(__file__).resolve().parents[1] / "evals" / "rag_cases.jsonl"


def test_rag_dataset_has_explicit_routing_categories() -> None:
    cases = load_rag_cases(CASES)
    assert len(cases) == 22
    assert sum(case["kind"] == "valid" for case in cases) == 18
    assert sum(case["kind"] == "expired" for case in cases) == 2
    assert sum(case["kind"] == "realtime" for case in cases) == 1
    assert sum(case["kind"] == "no_evidence" for case in cases) == 1


def test_retrieval_metrics_only_count_valid_questions() -> None:
    rows = [
        {"id": "a", "kind": "valid", "rank": 1},
        {"id": "b", "kind": "valid", "rank": 4},
        {"id": "c", "kind": "valid", "rank": None},
        {"id": "old", "kind": "expired", "rank": None},
        {"id": "realtime", "kind": "realtime", "rank": None},
    ]
    result = compute_retrieval_metrics(rows)
    assert result["valid_n"] == 3
    assert result["hit_at_1"] == 1 / 3
    assert result["hit_at_3"] == 1 / 3
    assert result["hit_at_5"] == 2 / 3
    assert result["mrr"] == (1 + 1 / 4) / 3
