"""A later evaluation run must not overwrite the frozen P2 evidence."""

from pathlib import Path

from scripts import evaluate_p2_faults, evaluate_p2_security


def test_security_runner_accepts_separate_cases_and_result_paths() -> None:
    args = evaluate_p2_security.parse_args(
        ["--cases", "/app/evals/p2_1.jsonl", "--output-json", "/app/reports/p2_1_security.json"]
    )

    assert args.cases == Path("/app/evals/p2_1.jsonl")
    assert args.output_json == Path("/app/reports/p2_1_security.json")


def test_fault_runner_accepts_separate_result_path() -> None:
    args = evaluate_p2_faults.parse_args(
        ["--output-json", "/app/reports/p2_1_faults.json"]
    )

    assert args.output_json == Path("/app/reports/p2_1_faults.json")
