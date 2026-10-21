"""Evaluate the P2 tenant's current Dense retrieval without an LLM judge."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
from typing import Any

from customer_service_app.core.config import get_settings
from customer_service_app.infrastructure.embeddings.factory import build_embedding_client
from customer_service_app.infrastructure.lexical_search import build_lexical_retriever
from customer_service_app.infrastructure.vector_store.factory import build_vector_store
from customer_service_app.services.rag_service import RagService


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "rag_cases.jsonl"
DEFAULT_JSON = ROOT / "reports" / "p2_rag_results.json"
DEFAULT_MD = ROOT / "reports" / "p2_rag_evaluation.md"
KINDS = {"valid", "expired", "realtime", "no_evidence"}


def load_rag_cases(path: Path) -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids: set[str] = set()
    for case in cases:
        if case.get("kind") not in KINDS or not case.get("id") or not case.get("query"):
            raise ValueError(f"Invalid RAG case: {case!r}")
        if case["id"] in ids:
            raise ValueError(f"Duplicate RAG case: {case['id']}")
        if case["kind"] in {"valid", "expired"} and not case.get("relevant_source"):
            raise ValueError(f"Missing relevant source: {case['id']}")
        ids.add(case["id"])
    return cases


def compute_retrieval_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row["kind"] == "valid"]
    n = len(valid)
    return {
        "valid_n": n,
        "hit_at_1": sum(row.get("rank") is not None and row["rank"] <= 1 for row in valid) / n if n else None,
        "hit_at_3": sum(row.get("rank") is not None and row["rank"] <= 3 for row in valid) / n if n else None,
        "hit_at_5": sum(row.get("rank") is not None and row["rank"] <= 5 for row in valid) / n if n else None,
        "mrr": sum(1 / row["rank"] for row in valid if row.get("rank")) / n if n else None,
    }


async def _close(resource: object) -> None:
    closer = getattr(resource, "close", None)
    if callable(closer):
        result = closer()
        if inspect.isawaitable(result):
            await result


async def evaluate(cases: list[dict[str, Any]], *, tenant_id: str, top_k: int) -> dict[str, Any]:
    settings = get_settings()
    embedding = build_embedding_client(settings)
    vector = build_vector_store(settings)
    lexical = build_lexical_retriever(settings)
    service = RagService(
        settings=settings, embedding_client=embedding, vector_store=vector,
        lexical_retriever=lexical, reranker=None,
    )
    mode = service._retrieval_mode()
    rows: list[dict[str, Any]] = []
    try:
        for case in cases:
            chunks = await service.retrieve(
                tenant_id=tenant_id, question=case["query"], top_k=top_k,
                use_rerank=False,
            )
            sources = [chunk.source for chunk in chunks]
            expected = case.get("relevant_source")
            rank = sources.index(expected) + 1 if expected in sources else None
            row = {
                "id": case["id"], "kind": case["kind"],
                "relevant_source": expected, "rank": rank,
                "sources": sources,
                "expired_source_exposed": case["kind"] == "expired" and expected in sources,
                "realtime_skipped": case["kind"] == "realtime" and not sources,
            }
            rows.append(row)
            print(json.dumps({"id": row["id"], "kind": row["kind"], "rank": rank}, ensure_ascii=False), flush=True)
    finally:
        for resource in (lexical, vector, embedding):
            await _close(resource)
    return {
        "metadata": {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "tenant_id": tenant_id, "top_k": top_k,
            "configured_mode": settings.retrieval_mode,
            "effective_mode": mode,
            "embedding_provider": settings.embedding_provider,
            "opensearch_enabled": settings.opensearch_enabled,
            "answer_faithfulness": "not_evaluated; requires human review",
        },
        "metrics": compute_retrieval_metrics(rows),
        "rows": rows,
    }


def render_markdown(data: dict[str, Any]) -> str:
    metrics = data["metrics"]
    lines = [
        "# P2 Dense RAG 检索评测（2026-10-21）", "",
        f"租户 `{data['metadata']['tenant_id']}`；配置 `{data['metadata']['configured_mode']}`，实际 `{data['metadata']['effective_mode']}`；OpenSearch `{data['metadata']['opensearch_enabled']}`；top_k={data['metadata']['top_k']}。", "",
        f"有效知识题 n={metrics['valid_n']}：Hit@1={metrics['hit_at_1']:.4f}，Hit@3={metrics['hit_at_3']:.4f}，Hit@5={metrics['hit_at_5']:.4f}，MRR={metrics['mrr']:.4f}。", "",
        "旧题集 Hit@5=0.65/MRR=0.60 含已过期来源，评测集不同，不能把差值解释为模型优化收益。", "",
        "| ID | 类别 | 相关来源排名 | Top-K 来源 |", "|---|---|---:|---|",
    ]
    for row in data["rows"]:
        lines.append(f"| {row['id']} | {row['kind']} | {row['rank'] or '—'} | {', '.join(row['sources']) or '—'} |")
    lines.extend(["", "过期题只检查过期来源不应露出；实时题只检查检索跳过；无依据题的最终回答安全性未由检索排名证明。回答事实准确性/忠实性未自动评分，需人工核对。", ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--tenant-id", default="p2-evaluation")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_MD)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    data = await evaluate(load_rag_cases(args.cases), tenant_id=args.tenant_id, top_k=max(args.top_k, 5))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_md.write_text(render_markdown(data), encoding="utf-8")
    print(json.dumps(data["metrics"], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
