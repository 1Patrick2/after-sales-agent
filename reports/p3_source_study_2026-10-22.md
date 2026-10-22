# Agent V2 源码学习导航（秋招面试版）

**目标：**先能沿真实调用链讲清一条业务请求，再拿 P0/P1/P2.1 的真实问题解释设计和边界。这里只列阅读顺序与追问，不是现成面试答案。所有示例使用本地合成数据；不把未启用的 MCP/Hybrid RAG 描述为已验证。

建议先看 [README 架构图](../README.md)，再按 Part 1→6 阅读。每个 Part 完成时，用自己的话画出输入、状态变化、外部依赖与异常出口；回答不出来再看相应报告，不要背术语。

## Part 1：整体架构与 FastAPI 入口

**读：**`src/customer_service_app/main.py::create_app` → `api/routes_chat.py::chat` → `api/dependencies.py` → `services/container.py::ApplicationContainer.create/build_agent` → `services/customer_service_agent.py::CustomerServiceAgent.answer/_answer_unlocked` → `domain/schemas.py::ChatRequest/ChatResponse`。

**抓住：**路由只做请求校验和身份解析；门面提交 Graph；返回体同时有用户答复和可验证的 `run_id/thread_id/trace`。`conversation_id` 是业务会话，`thread_id` 是 Graph checkpoint 线程，不可混用。

**五个追问：**

1. 一个 `POST /api/v1/chat` 从 HTTP 到 Graph 的对象创建与调用顺序是什么？
2. 为什么 `ChatRequest` 同时需要 `conversation_id` 和 `thread_id`？第二轮漏一个会怎样？
3. 何时返回 `waiting_confirmation`，何时返回 `completed` 或 `needs_clarification`？
4. `ApplicationContainer` 中有哪些外部客户端，生命周期如何关闭？
5. `SECURITY_ENABLED=false` 时请求内 `user_id` 是否可信？开启 JWT 后 `authorize_identity` 做了什么？

## Part 2：LangGraph、State、Router 与 Planner

**读：**`workflows/state.py::CustomerServiceGraphState` → `workflows/customer_service_graph.py::build_customer_service_graph` → `workflows/nodes.py::CustomerServiceGraphNodes.prepare/rewrite/retrieve/evaluate_retrieval/decide/execute_plan_step` → `services/question_router.py::QuestionRouter.route/should_plan` → `services/planner_service.py::PlannerService.needs_plan/build_plan/_normalize_llm_plan/build_rule_based_plan`。

**抓住：**图定义节点与可能去向；节点返回 `Command(goto=...)` 实际控制下一步。Planner 是复杂任务的有界结构化计划，简单请求可能直接由模型 Tool Calling；`origin` 明确标出 `llm_generated`、`llm_repaired`、`rule_fallback`。路由使用原句与改写句，避免 R06 的原始提交意图丢失。

**五个追问：**

1. State 中哪些是用户输入，哪些是节点派生的可信/不可信状态？为什么要限制递归和工具调用数？
2. 图节点的 `RetryPolicy(max_attempts=2)` 作用于哪类异常？为什么不能把它当成上游总请求次数？
3. Planner 的 `submit_plan` 结构化输出经哪些校验？为什么计划校验通过仍不能直接执行写入？
4. 什么时候走 Planner，什么时候走首轮模型 Tool Calling？R03/R06 先前为什么没进确认？
5. `llm_repaired` 与 `rule_fallback` 在 Trace 和面试表述上有什么区别？

## Part 3：Tool Calling、Registry 与业务边界

**读：**`services/tool_registry.py::ToolSpec.as_openai_tool/ToolRegistry.register/definitions/execute/_validate_arguments` → `tools/default_registry.py::build_default_tool_registry` → `tools/after_sales_tools.py` → `services/business_gateway.py::BusinessGateway.query_order_status/query_logistics_status/create_refund_case` → `infrastructure/db/repositories.py::OrderRepository.get_by_order_id/TicketRepository.create`。

**抓住：**模型给出工具名和 JSON 参数只是**提议**；后端负责 schema、超时、身份上下文、风险等级和业务事实。`create_refund_case` 查询订单归属并以确认 ID 形成唯一键；Tool Calling 的参数不能决定真实租户身份。

**五个追问：**

1. `ToolSpec` 如何转成模型能见的 JSON Schema，模型返回无效 JSON 时在哪里拒绝？
2. `asyncio.wait_for` 工具超时能否保证外部业务系统没有写入？为什么不能？
3. `query_order_status` 与 `query_logistics_status` 各自应该回答什么？C05 为什么算严格工具选择失败？
4. 为什么要有 `BusinessGateway` 而不让模型/工具直接写 `SupportTicket`？
5. `refund:<confirmation_id>` 能防止哪些重放？同一订单新建另一个 confirmation ID 时还缺什么策略？

## Part 4：RAG、Embedding、过滤与 Bad Case

**读：**`scripts/ingest_docs.py::ingest` → `services/question_rewrite_service.py::QuestionRewriteService.resolve` → `services/question_router.py::QuestionRouter.route/_document_types` → `services/rag_service.py::RagService.retrieve/_dense_search/_retrieval_mode/_rrf/evaluate_quality` → `workflows/nodes.py::CustomerServiceGraphNodes.retrieve/evaluate_retrieval/finalize` → `scripts/evaluate_p2_rag.py`。

**抓住：**当前 Ollama `qllama/bge-small-zh-v1.5:q8_0` 输出 512 维，Qdrant Dense 实测；配置名 `hybrid` 不意味着 OpenSearch/BM25 已开启。检索有租户/文档类型/有效期约束，Top-K 命中与最终回答正确是两个指标。

**五个追问：**

1. 中文 Embedding 选型为什么优先考虑语种、维度、语义检索任务与本机资源，而不是“模型越大越好”？
2. K02 为什么属于路由/文档类型过滤问题，而非纯 Embedding 召回失败？
3. K01 已命中正确政策，为何仍只能判 Partial？如何分别评估 Hit@K 与 Faithfulness/完整性？
4. RAG 一路检索失败和两路都失败时，代码如何降级或报错？本次实测覆盖到什么程度？
5. Hit@1、Hit@5、MRR 各自表达什么；为何不同有效期题集的两个分数不能直接宣称优化收益？

## Part 5：人工确认、Checkpoint、幂等与安全恢复

**读：**`workflows/nodes.py::CustomerServiceGraphNodes.create_pending_action/await_confirmation/apply_confirmation` → `workflows/runtime.py::CustomerServiceGraphRuntime.create/invoke/resume` → `api/routes_confirmations.py::approve_confirmation/reject_confirmation` → `services/customer_service_agent.py::CustomerServiceAgent._resume_confirmation_unlocked` → `services/confirmation_service.py::ConfirmationService.approve/reject` → `infrastructure/db/repositories.py::PendingActionRepository.claim_for_approval/TicketRepository.get_by_idempotency_key` → `api/routes_graph.py::get_graph_thread`。

**抓住：**Pending 在 MySQL，`interrupt` 的执行位置在 PostgreSQL Checkpoint；批准接口用确认单保存的原 `langgraph_thread_id` 发 `Command(resume=...)`。拒绝不写入，批准才进入 BusinessGateway。MySQL 与 PostgreSQL 非同一事务，仍有跨库窗口。隔离 JWT 验证与常驻服务配置分开表述。

**五个追问：**

1. 为何人工确认必须是 Graph 的 `interrupt`，而不是模型回复一句“请确认”？
2. API 容器重启后如何找到原执行位置？如果只保存 `conversation_id` 而没有原 `thread_id` 会怎样？
3. 批准前工单为何应为 0？重复批准为何应 409 且工单仍为 1？
4. MySQL 工单已提交、PostgreSQL checkpoint 未同步或反向发生时，会留下什么不一致？现有代码是否自动对账？
5. P1 的 Graph 快照越权为何要用持久化 run owner 修复？常驻 `SECURITY_ENABLED=false` 的结论边界是什么？

## Part 6：固定集评测、性能口径与项目贡献

**读：**`evals/agent_cases.jsonl`、`evals/agent_cases_p2_1_final_2026-10-22.jsonl` → `scripts/evaluate_agent.py::run_live/summarize` → `scripts/evaluate_p2_security.py`、`scripts/evaluate_p2_faults.py` → `reports/p2_1_agent_optimization_2026-10-22.md` → [P3 贡献索引](p3_contributions_2026-10-22.md)。

**抓住：**40 例最终“自动 28 Pass/2 Fail/10 Review”与“人工 37 Pass/2 Fail/1 Partial”是不同口径；网络 34、隔离 JWT 4、Mock 故障 2。`153 passed, 3 skipped` 是代码测试，不是 153 个真实业务场景。P50/P95 是串行 HTTP 请求延迟，不是吞吐或生产 SLA。

**五个追问：**

1. 为什么把 `needs_review` 直接算成功会夸大成功率？人工裁定如何保留可追溯证据？
2. 37/40 能否写成“模型任务成功率 92.5%”？为什么分母中的 JWT/Mock 与单次随机性都要说明？
3. P50/P95、任务成功率、工具参数有效率、RAG Hit@K/MRR 分别衡量哪个层次？
4. 如何用 R05、C05、K01 解释业务安全、工具选择与回答完整性的不同失败？
5. 哪些设计属于原仓库，哪些是 `origin/master..HEAD` 六个提交里的增量？简历上如何准确说“二次开发”？

## 建议学习节奏

第 1 次：Part 1–3，自己画一条订单查询链和一条退款规划链；第 2 次：Part 4–5，拿 K02/R06/P0 重启恢复讲错误定位；第 3 次：Part 6，按实际证据做 5 分钟演示和模拟追问。此阶段不继续扩展功能。
