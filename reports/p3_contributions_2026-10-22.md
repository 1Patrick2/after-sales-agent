# P3 二次开发贡献与面试证据索引

## 归属口径

本项目基于已有开源仓库。当前 `origin/master` 为 `c1db4a4f363cb72c4b31ef739c27142c4a26c429`；本地 `codex/refund-hil-p0` 到 P2.1 的可核对增量为其后的六个提交：`8d93f29`、`81e647b`、`8f09a10`、`35bbb13`、`80b4c17`、`919f4fb`。`35bbb13` 仅为 P1 报告修订。下表只将这些提交及报告可证明的**本地二次开发工作**列为增量；不能把原仓库的 FastAPI、LangGraph 总体设计、RAG/MCP 代码框架、已有业务工具与原有测试写成从零原创。提交归属和个人实际参与方式在简历中仍应实事求是表述为“基于开源项目二次开发与验收”。

## 可以讲的真实增量

| 原问题与阶段 | 增量代码/核心函数 | 解决方式与证据 | 关键词与面试追问 |
|---|---|---|---|
| P0：退款申请常被当作只读查询；批准时 ORM 读取 server default 触发 `MissingGreenlet`、时间戳 naive/aware 异常 | `services/question_router.py::QuestionRouter.route`；`infrastructure/db/repositories.py::PendingActionRepository.create/claim_for_approval`；`services/confirmation_service.py::ConfirmationService._is_expired`；`workflows/nodes.py::CustomerServiceGraphNodes.apply_confirmation`；`8d93f29` | 明确写入意图进入 Planner/HIL，flush 后刷新默认值、统一 UTC 比较，批准后重建最终答复；P0 报告的批准单 0→1、拒绝单 0、跨 app 重启恢复，相关回归在 `tests/test_pending_action_db.py`、`tests/test_refund_resume_response.py` | Async ORM、时区、LangGraph interrupt。为什么 flush 后访问默认列会触发隐式 IO？ |
| P0：退款写工具未在业务边界复核订单归属，重复批准可返回旧 200 | `services/business_gateway.py::BusinessGateway.create_refund_case`；`services/customer_service_agent.py::CustomerServiceAgent._resume_confirmation_unlocked`；`8d93f29` | 在写入前按 tenant/user/order 查 MySQL；确认状态非 pending 返回 409。P0 DB/Trace 与 `tests/test_refund_order_guard.py` 验证未授权订单不创建工单 | 后端信任边界。为何不能相信 LLM 传来的 tenant/user/order 参数？ |
| P1：Graph 快照接口原依赖已脱敏 state 判归属，可能漏掉授权 | `api/routes_graph.py::get_graph_thread`；`81e647b` | 改用 checkpoint 的 run_id 反查持久化 Agent Run，再核对 tenant/user；`tests/test_graph_thread_authorization.py` 曾先复现越权，再验证 403/404 | IDOR、对象级授权。为什么“已脱敏的快照”仍需要访问控制？ |
| P1：同一确认可能因重复恢复或并发造成重复写入；模型底层异常可能回显敏感内容 | `tools/after_sales_tools.py`、`services/business_gateway.py::create_refund_case`、`infrastructure/db/repositories.py::TicketRepository`、`infrastructure/llm/openai_compatible.py`；`8f09a10` | 从可信确认上下文传 `confirmation_id`，工单唯一键 `refund:<confirmation_id>`；先查重并校验关联订单。模型错误改为通用类型，不回显底层异常。`tests/test_refund_write_idempotency.py`、`tests/test_p1_confirmation_concurrency_db.py`、`tests/test_p1_fault_boundaries.py` 及 P1 报告 | 幂等、并发 CAS、脱敏。数据库唯一键能防什么，跨 MySQL/PostgreSQL 还会留下什么窗口？ |
| P2：缺可重复业务证据，旧测试通过数不能代表真实任务成功率 | `scripts/evaluate_agent.py`、`scripts/evaluate_p2_rag.py`、`scripts/collect_p2_trace_evidence.py`、`evals/agent_cases.jsonl`、`evals/rag_cases.jsonl`；`80b4c17` | 建立 40 场景固定集、18 个有效知识题 Dense 指标、HTTP/Trace/DB 交叉证据；保留失败与待复核。原自动 24/9/7，旧事后人工 31/9。报告 `p2_agent_evaluation_2026-10-21.md` | Agent 评测、分母、Hit@K/MRR、P95。为什么 87 个单元测试通过不等于 87 个业务场景成功？ |
| P2.1：R03/R07/R08 明确退款申请被降成只读工具；K02/K03/K07 政策路由错误；C02 已有订单仍追问；R06 改写丢失原始提交意图 | `services/question_router.py::QuestionRouter.route/should_plan`、`services/question_rewrite_service.py::QuestionRewriteService.resolve`；`919f4fb` | 保留原句写入/政策意图，收窄只读问题的多余澄清清除；先失败后通过的回归见 `tests/test_question_router.py`、`tests/test_question_rewrite_service.py`。最终 R06 Pending→批准→DB 0→1；原九项严格失败中七项改变为通过，R05/C05 保留失败 | 意图路由、改写安全性。为什么 LLM 改写后的文本不能成为唯一授权依据？ |
| P2.1：无法分辨计划是 LLM 一次生成、修复生成或规则回退 | `domain/planning.py::AgentPlan.origin`、`services/planner_service.py::PlannerService.build_plan`、`workflows/nodes.py::CustomerServiceGraphNodes.decide`；`919f4fb` | Trace 写 `llm_generated` / `llm_repaired` / `rule_fallback`。最终退款图快照中 5 个原生生成、2 个修复生成、R05 未生成计划；没有把规则回退混称为 LLM 自主规划 | 可观测性、Fallback。模型计划经 JSON Schema 校验后为何仍需后端工具权限治理？ |

P1 的独立 JWT 测试验证了自有/他人订单访问和确认单归属，**不是**把常驻 `SECURITY_ENABLED=false` 服务改成可公开部署。P1 并发测试只证明确认单领取边界，不是并发完整退款写入验收。P2/P2.1 的费用与上游模型请求次数未从 HTTP 次数推断。

## 指标与边界速查

| 证据 | 实际结果 | 正确讲法 |
|---|---|---|
| P0 默认回归 | 99 passed；跨 API 重启后 PostgreSQL checkpoint 恢复批准，工单 0→1 | “本地模拟业务闭环验收”，不是生产支付退款 |
| P1 默认回归 | 120 passed、3 skipped；隔离 JWT、单确认幂等与并发领取有独立证据 | “分层验证可靠性”，不是全局 exactly-once |
| P2 固定集 | 40 例；自动 24 Pass/9 Fail/7 Review；事后人工 31 Pass/9 Fail | Review 没核对前不计自动 Pass |
| P2.1 最终固定集 | 网络 34 例自动 22/2/10；隔离 JWT 4 Pass、Mock 故障 2 Pass；合并自动 28/2/10，人工 37 Pass/2 Fail/1 Partial | 单次混合集人工裁定，不能写“真实 LLM 稳定成功率 92.5%” |
| P2.1 默认回归 | 153 passed、3 skipped；passlib `crypt` 弃用警告 1 条 | 单元/集成测试通过，非生产 SLA |
| Dense RAG | 有效知识题 n=18；Hit@1 0.5556、Hit@5 0.6667、MRR 0.6111 | 检索指标，不是回答忠实性；OpenSearch 关闭 |
| 延迟 | 最终网络 65 个 HTTP 请求，P50 3879.33 ms、P95 15947.52 ms | 本地串行评测请求延迟，不是 QPS/上线性能 |

证据文件：[P0](p0_refund_hil_acceptance_2026-10-21.md)、[P1](p1_security_reliability_2026-10-21.md)、[P2](p2_agent_evaluation_2026-10-21.md)、[P2.1](p2_1_agent_optimization_2026-10-22.md)、[最终 34 例网络结果](p2_1_final_network_2026-10-22.json)、[Dense RAG](p2_1_rag_2026-10-22.md)。P0/P1/P2 已有的报告数字不可与不同版本的单次样本直接做稳定性能趋势。

## 最值得面试展开的三个真实问题

1. **P0 创建与批准退款的两处故障：ORM/时区/恢复联动。** 首先，创建 Pending 时因读取 MySQL server default 触发异步 ORM 的 `MissingGreenlet`；修复后又在批准/恢复阶段发现时间戳 naive/aware 比较和最终回复问题。最终用同一 thread checkpoint 恢复，确认单 `executed`、工单 0→1、重复批准 409。追问：MySQL 与 PostgreSQL 不共享事务时，任意一步提交失败怎么办？答案应承认仍有对账/补偿缺口。
2. **P1 Graph 快照 IDOR。** 现象是快照经过脱敏后无法可靠提供 tenant/user，旧接口可能绕过归属判断。改为通过持久化 `run_id` 查询所有者再授权；隔离 JWT 用例校验 403/404。追问：为何“只读”接口同样属于敏感面？因为线程状态、计划与 Trace 仍可暴露业务关系和执行轨迹。
3. **P2.1 原始退款命令被改写成政策咨询。** R06 原句要求提交申请，独立改写却变成“如何提交”，只看改写后的路由曾不创建 Pending。保留原始动作意图后，真实复测进入确认，批准的模拟订单 DB 0→1。追问：原句和改写句冲突时谁是权威？后端必须保存用户原始授权意图，改写仅补充实体和检索词；写操作仍需参数/身份校验与人工确认。

仍需坦诚的 Bad Case：R05 因缺退款原因而停在安全澄清，严格固定判据 Fail；C05 选 `query_order_status` 而非预期物流工具，即使回答含正确运单号也仍 Fail；K01 正确来源已命中，但漏答明确“7 天”，只计 Partial。
