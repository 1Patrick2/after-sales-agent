"""Merge P2 evidence while keeping network, isolated JWT, and Mock results distinct."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from scripts.evaluate_agent import load_cases, percentile, summarize


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "agent_cases.jsonl"
MAIN = ROOT / "reports" / "p2_agent_results.json"
SECURE = ROOT / "reports" / "p2_security_results.json"
FAULT = ROOT / "reports" / "p2_fault_results.json"
RERUN = ROOT / "reports" / "p2_agent_rescore_results.json"
REFUND_AUDIT = ROOT / "reports" / "p2_refund_db_audit.json"
RAG = ROOT / "reports" / "p2_rag_results.json"
TRACE = ROOT / "reports" / "p2_trace_evidence.json"
MERGED = ROOT / "reports" / "p2_all_results.json"
REPORT = ROOT / "reports" / "p2_agent_evaluation_2026-10-21.md"
LATENCY = ROOT / "reports" / "p2_latency_analysis.md"


def combine_results(
    cases: list[dict[str, Any]], main: list[dict[str, Any]],
    secure: list[dict[str, Any]], mock: list[dict[str, Any]],
    rerun: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    expected_ids = [case["case_id"] for case in cases]
    main_ids = [row["case_id"] for row in main]
    if len(main_ids) != len(set(main_ids)):
        raise ValueError("Duplicate main result")
    if set(main_ids) != set(expected_ids):
        raise ValueError("Main result set does not match fixed case set")
    by_id = {row["case_id"]: row for row in main}
    for row in rerun or []:
        case_id = row["case_id"]
        if case_id not in by_id or by_id[case_id]["status"] == "not_run":
            raise ValueError(f"Unexpected rerun case: {case_id}")
        prior = by_id[case_id]
        by_id[case_id] = {**row, "previous_status": prior["status"],
                          "previous_failure_type": prior.get("failure_type"),
                          "rerun_reason": "corrected multi-turn graph-status scoring"}
    for source, rows in (("secure", secure), ("mock", mock)):
        seen: set[str] = set()
        for row in rows:
            case_id = row["case_id"]
            if case_id in seen:
                raise ValueError(f"Duplicate {source} result: {case_id}")
            seen.add(case_id)
            if case_id not in by_id or by_id[case_id]["status"] != "not_run":
                raise ValueError(f"Unexpected {source} replacement: {case_id}")
            by_id[case_id] = row
    return [by_id[case_id] for case_id in expected_ids]


def _latency_stats(values: list[float]) -> dict[str, Any]:
    return {
        "request_count": len(values),
        "mean": round(sum(values) / len(values), 2) if values else None,
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
    }


def latency_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    network_modes = {"chat", "refund", "http_negative"}
    all_network = [
        float(latency) for result in results if result.get("mode") in network_modes
        for latency in result.get("latencies_ms", [])
    ]
    chat = [
        float(latency) for result in results if result.get("mode") in {"chat", "refund"}
        for latency in result.get("latencies_ms", [])[:len(result.get("responses", []))]
    ]
    return {
        "real_network_all_api": _latency_stats(all_network),
        "real_network_chat": _latency_stats(chat),
        "isolated_in_process_jwt": _latency_stats([
            float(latency) for result in results if result.get("mode") == "isolated_jwt_http"
            for latency in result.get("latencies_ms", [])
        ]),
        "mock_regression_wall_time": _latency_stats([
            float(latency) for result in results if result.get("mode") == "mock_regression"
            for latency in result.get("latencies_ms", [])
        ]),
    }


def _category_summary(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for result in results:
        grouped[result["category"]][result["status"]] += 1
    return {category: dict(counter) for category, counter in sorted(grouped.items())}


def _tool_selection_summary(cases: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, int]:
    by_id = {case["case_id"]: case for case in cases}
    eligible = [row for row in results if by_id[row["case_id"]].get("expected_tool") and row["status"] != "not_run"]
    selected = sum(
        any(item.get("name") == by_id[row["case_id"]]["expected_tool"] and item.get("ok") is True
            for response in row.get("responses", []) for item in response.get("tool_results", []))
        for row in eligible
    )
    return {"evaluated": len(eligible), "expected_tool_executed_ok": selected}


def render_report(
    cases: list[dict[str, Any]], results: list[dict[str, Any]], metadata: dict[str, Any],
    refund_audit: list[dict[str, Any]] | None = None,
    rag_metrics: dict[str, Any] | None = None,
    trace_evidence: dict[str, Any] | None = None,
) -> str:
    summary = summarize(results)
    categories = _category_summary(results)
    modes = Counter(row.get("mode", "unknown") for row in results)
    tools = _tool_selection_summary(cases, results)
    network = [row for row in results if row.get("mode") in {"chat", "refund", "http_negative"}]
    network_summary = summarize(network)
    lines = [
        "# P2 Agent 端到端评测与量化分析（2026-10-21）", "",
        "## 范围与证据边界", "",
        f"固定用例 {len(cases)}；已尝试 {summary['attempted']}，确定通过 {summary['pass']}，失败 {summary['fail']}，待人工复核 {summary['needs_review']}，未执行 {summary['not_run']}。保守确认成功率 {summary['confirmed_success_rate']}，分母包含待复核。",
        "这不是单一的 40 条真实模型成功率：安全用例在独立 JWT TestClient 运行，故障注入含 Mock 单测；请按下面的来源分开解释。", "",
        f"常驻服务真实网络部分单列：{network_summary['attempted']} 例，确定通过 {network_summary['pass']}，失败 {network_summary['fail']}，待复核 {network_summary['needs_review']}；这些场景也并非每例都调用模型（含参数校验与 404）。", "",
        f"Git `{metadata['git_head']}`；模型 `{metadata['model']}`；固定种子 `{metadata['seed']}`；常驻服务 `SECURITY_ENABLED={metadata['security_enabled']}`；配置检索 `{metadata['retrieval_mode_configured']}`，OpenSearch `{metadata['opensearch_enabled']}`；真实 HTTP 串行执行。",
        f"真实网络执行器 HTTP 请求 {metadata['actual_http_requests']} 次；这不是上游 LLM 请求数，中转站费用不可由本报告推断。", "",
        "另有 C02/C06 重跑 4 次 HTTP、已落盘的 pilot 3 次 HTTP，以及首次因容器缺 git 导致报告未落盘的 pilot 5 次 HTTP；这些开发/诊断请求不计入固定 40 例的成功率。", "",
        "C02/C06 因首版评测器把中间澄清误判为图错误而按修正判据独立重跑；原结果保留在 `p2_agent_results.json`，重跑证据在 `p2_agent_rescore_results.json`。C02 重跑仍失败，C06 改为待人工复核；不可把重跑抹成首次成功。", "",
        "## 分组结果", "", "| 类别 | 通过 | 失败 | 待人工复核 | 未执行 |", "|---|---:|---:|---:|---:|",
    ]
    for category, counts in categories.items():
        lines.append(f"| {category} | {counts.get('pass', 0)} | {counts.get('fail', 0)} | {counts.get('needs_review', 0)} | {counts.get('not_run', 0)} |")
    lines.extend([
        "", "## 工具与数据正确性", "",
        f"明确标注期望工具的已尝试场景 {tools['evaluated']} 例，其中执行结果中可见期望工具且 `ok=true` 的 {tools['expected_tool_executed_ok']} 例。此值是工具执行可见率，不等同参数完全准确率；错误参数另以失败分类和逐例证据判断。",
        "退款场景只有在 Pending Action、Graph 中断、批准/拒绝状态及 MySQL 工单数量一致时才判通过；‘提交退款’只意味着申请工单，不代表支付退款。", "",
        "退款失败的主要现象是 R03/R05/R07/R08 仅查订单或进入澄清，未创建 Pending Action。原因尚需针对规划/意图进一步诊断，不把它包装成已修复。", "",
        "## 执行来源", "", f"`{json.dumps(dict(modes), ensure_ascii=False)}`", "",
        "## 失败分布", "", f"`{json.dumps(summary['failure_types'], ensure_ascii=False)}`", "",
        "知识类 3 例来源未命中，多轮类 1 例目标工具未出现、1 例仍需澄清；退款类 4 例未触发确认。未发现本轮退款失败例的意外工单写入。", "",
        "## 逐例可复核索引", "", "| Case | 状态 | 环境/模式 | 原因 | run_id | confirmation_id | DB 前→后 |", "|---|---|---|---|---|---|---|",
    ])
    for row in results:
        responses = row.get("responses", [])
        run_id = row.get("run_id") or next((r.get("run_id") for r in reversed(responses) if r.get("run_id")), "—")
        confirmation_id = row.get("confirmation_id") or "—"
        before = row.get("refund_tickets_before", "—")
        after = row.get("refund_tickets_after", "—")
        lines.append(f"| {row['case_id']} | {row['status']} | {row.get('mode', '—')} | {row.get('failure_type') or '—'} | {run_id} | {confirmation_id} | {before}→{after} |")
    if refund_audit is not None:
        lines.extend(["", "## 退款 MySQL 只读复核", "", "| Case | 退款申请工单数 | 确认单状态 |", "|---|---:|---|"])
        for row in refund_audit:
            lines.append(f"| {row['case_id']} | {row['refund_ticket_count']} | {', '.join(row['confirmation_statuses']) or '无'} |")
    if trace_evidence is not None:
        retrieved = sum(item.get("run_id") is not None for item in trace_evidence.values())
        lines.extend([
            "", "## 持久化 Trace 交叉核对", "",
            f"按本次结果中的 run_id 只读获取 {retrieved}/{len(trace_evidence)} 条 Agent Run；脱敏证据见 `p2_trace_evidence.json`，仅保留步骤状态、工具名、found 布尔值和合成订单号，不保存自由文本载荷。",
            "例如 O01 自有订单的 `query_order_status.found=true`，I02 跨用户查同一合成订单的 `found=false`；这两项不靠聊天文案判断。", "",
        ])
        lines.extend(["### 知识失败的上游路由证据", "", "| Case | 路由来源 | 允许文档类型 | 检索块数 |", "|---|---|---|---:|"])
        for row in results:
            if row.get("failure_type") != "retrieval_miss":
                continue
            run_id = next((item.get("run_id") for item in reversed(row.get("responses", [])) if item.get("run_id")), None)
            trace = trace_evidence.get(run_id, {})
            route = next((step.get("retrieval_route") for step in trace.get("steps", []) if step.get("retrieval_route")), {})
            lines.append(f"| {row['case_id']} | {route.get('source', '—')} | {', '.join(route.get('document_types', [])) or '—'} | {route.get('chunk_count', '—')} |")
        lines.extend(["", "K03/K07 被规则路由到实时工具而未检索；K02 的文档类型过滤不含目标政策类。它们是路由/过滤失误，不可全部算作 embedding 召回问题。", ""])
    if rag_metrics is not None:
        lines.extend([
            "", "## Dense RAG 单独基线", "",
            f"有效知识 {rag_metrics['valid_n']} 题：Hit@1={rag_metrics['hit_at_1']:.4f}，Hit@3={rag_metrics['hit_at_3']:.4f}，Hit@5={rag_metrics['hit_at_5']:.4f}，MRR={rag_metrics['mrr']:.4f}。详见 `p2_rag_evaluation.md`；回答忠实性未人工核验，不报分。", "",
            "实际为 Dense；旧题集包含过期来源，分数不可直接对比。", "",
        ])
    lines.extend([
        "", "## 本轮新增与遗留风险", "",
        "原项目已具有 FastAPI/LangGraph/HIL/Checkpoint/RAG/业务工具；本轮新增固定用例、执行器、P2 合成数据、Dense 检索与延迟统计，不将旧实现写为本轮原创。",
        "本报告未验证跨 MySQL/PostgreSQL 全局 exactly-once、常驻服务开启鉴权、真实外部服务故障窗口或公开生产部署。语义待人工复核不算已确认成功。模型规划与规则回退未逐例独立确认，不能把所有工具调用称为模型自主选择。", "",
        "P3 干净部署与冻结的前提：解释并修复影响主链路的失败、补人工回答忠实性核验、明确常驻 JWT 配置与跨库一致性限制；本轮不自行进入 P3。", "",
    ])
    return "\n".join(lines)


def render_latency(data: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# P2 API 延迟分析（2026-10-21）", "",
        "串行、固定本地 Docker 环境；记录客户端观测的端到端 HTTP 响应时间。不是模型底层 TTFT、TPOT、吞吐或生产 SLA。", "",
        "| 样本 | n | Mean ms | P50 ms | P95 ms |", "|---|---:|---:|---:|---:|",
    ]
    for label, key in (("真实网络所有 API", "real_network_all_api"), ("真实网络 POST /chat", "real_network_chat"), ("隔离 JWT 进程内 ASGI", "isolated_in_process_jwt"), ("Mock 测试墙钟耗时（非 API）", "mock_regression_wall_time")):
        stats = data[key]
        lines.append(f"| {label} | {stats['request_count']} | {stats['mean']} | {stats['p50']} | {stats['p95']} |")
    timeouts = sum(row.get("failure_type") == "timeout" for row in results)
    lines.extend(["", f"超时用例 {timeouts}；若请求在客户端超时前未返回，执行器没有该请求完整响应耗时，故上表样本可能低估尾延迟。小样本 P95 仅为本次观测，不提供 SLA 解释。", "", "每条用例的每次请求耗时见 `p2_all_results.json`；退款用例的 `latencies_ms` 顺序依次为聊天、Graph/确认查询、确认操作。报告没有在负载测试中并行运行 Dense RAG 专项。", ""])
    return "\n".join(lines)


def main() -> None:
    cases = load_cases(CASES)
    main_data = json.loads(MAIN.read_text(encoding="utf-8"))
    secure_data = json.loads(SECURE.read_text(encoding="utf-8"))
    fault_data = json.loads(FAULT.read_text(encoding="utf-8"))
    rerun_data = json.loads(RERUN.read_text(encoding="utf-8"))
    refund_audit = json.loads(REFUND_AUDIT.read_text(encoding="utf-8"))
    rag_data = json.loads(RAG.read_text(encoding="utf-8"))
    trace_data = json.loads(TRACE.read_text(encoding="utf-8"))
    results = combine_results(
        cases, main_data["results"], secure_data["results"],
        fault_data["results"], rerun=rerun_data["results"],
    )
    data = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "metadata": main_data["metadata"],
        "summary": summarize(results),
        "by_category": _category_summary(results),
        "by_mode": dict(Counter(row.get("mode", "unknown") for row in results)),
        "tool_selection": _tool_selection_summary(cases, results),
        "latency": latency_summary(results),
        "refund_db_audit": refund_audit,
        "rag_metrics": rag_data["metrics"],
        "trace_runs_retrieved": sum(item.get("run_id") is not None for item in trace_data.values()),
        "results": results,
    }
    MERGED.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT.write_text(render_report(cases, results, main_data["metadata"], refund_audit, rag_data["metrics"], trace_data), encoding="utf-8")
    LATENCY.write_text(render_latency(data["latency"], results), encoding="utf-8")
    print(json.dumps(data["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
