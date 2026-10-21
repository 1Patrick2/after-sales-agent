# P1 Agent 安全性与可靠性验收（2026-10-21）

## 结论与范围

唯一仓库 `enterprise-customer-service-agent-v2`，本地合成订单、模拟退款**申请工单**；没有真实支付退款、生产数据、MCP 扩展或混合检索改造。本轮完成了真实 JWT 的隔离测试、Graph 快照越权修复、退款工单确认 ID 幂等键、模型错误脱敏与受控故障测试。不能据此称为生产就绪或跨 MySQL/PostgreSQL 的全局 exactly-once。

常驻 `ecs_app` 仍为 `SECURITY_ENABLED=false` 的本地演示配置；真实鉴权测试在一次性 `SECURITY_ENABLED=true` 的 TestClient 进程中运行，JWT 密钥每次临时生成，未修改 `.env`。Python 3.11 容器测试使用只读源码挂载。六个服务（app、MySQL、PostgreSQL、Redis、Qdrant、Ollama）运行，P1 源码挂载后的 app 重启并最终 `/health/ready=200`。首次重启后立即请求遇到短暂连接重置，随后就绪；不可把此现象当成业务故障。干净镜像重建仍未验。

P0 基线为 99 passed。B 阶段为 109 passed、2 skipped；P1 当前默认套件为 **120 passed、0 failed、3 skipped、1 warning**。跳过项是显式门控的真实 JWT 读测试、一次性真实 JWT 写测试和 MySQL 并发领取测试；它们已在独立进程分别执行，均为 1 passed。完整套件的 warning 来自 passlib 对 Python `crypt` 的弃用引用，不是业务失败。

## B：鉴权与隔离

| 用例 | 结果与证据 | 关键实现 |
| --- | --- | --- |
| B1 无认证 | PASS：确认单 GET 401 `authentication_required`；Graph GET 单测亦 401 | `api/dependencies.py`、`core/security.py` |
| B2 错误凭证 | PASS：无效 Bearer 403 `permission_denied` | 同上；`tests/test_p1_auth_live.py` |
| B3 自有订单 | PASS：真实 LLM/`query_order_status` 对自有订单 `202610210003` 返回 `found=true`，HTTP 200 | `BusinessGateway.query_order_status`、`OrderRepository.get_by_order_id` |
| B4 他人订单自然语言 | PASS：另一客户问同一订单，HTTP 200 但工具结果 `found=false`，未返回订单事实 | 同上 |
| B5 直接指定外部订单号 | PASS：A 指定 B 的订单 `202610210102`，`found=false`；B 查本单 `found=true` | 同上；`tests/test_p1_auth_live.py` |
| B6 他人确认单 | PASS：外部客户 approve/reject 均 404 `confirmation_not_found`；无工单写入 | `ConfirmationService.get_owned`、`routes_confirmations.py` |
| B7 跨租户 | PASS：请求身份租户不匹配 403；A 查 B 订单 `found=false`；外租户 operator 读 Graph 403。Graph 漏洞修复前同一请求曾 200 | `routes_graph.get_graph_thread` 从 `AgentRunRepository.get_run` 取得持久化归属后授权 |
| B8 模型伪造身份/参数 | PASS（已测边界）：JSON Schema `additionalProperties=false` 阻止模型提交 `tenant_id/user_id`；工具使用后端 `ToolExecutionContext`；错误订单由仓库归属查找阻止。未枚举所有提示注入变体 | `ToolRegistry._validate_arguments`、`tools/after_sales_tools.py`、`BusinessGateway` |
| B9 合法退款写入 | PASS：真实 JWT + LLM 对新合成订单 `202610210103` 创建 Pending Action、批准 HTTP 200、重复批准 HTTP 409；MySQL 仅一条退款申请工单 | `tests/test_p1_auth_live.py`；下方数据库对照 |

真实鉴权测试没有改动常驻演示 API 的安全开关。不能把此测试解释为公开部署已开启鉴权。测试身份和订单均为合成数据。

## C：故障注入与可靠性

| 用例 | 结果、触发方式与业务影响 |
| --- | --- |
| C1 模型异常/超时 | PARTIAL：Mock 模型抛 `ExternalServiceError`，Planner 一次失败转规则计划，退款步骤仍 `requires_confirmation`，未执行工具；OpenAI-compatible 错误被统一为 502 类型 `ExternalServiceError`，不回显底层异常。配置 `llm_timeout_seconds` 和 Graph `RetryPolicy(max_attempts=2, retry_on=ExternalServiceError)` 存在，但未对真实网络超时执行端到端故障注入；OpenAI SDK 本身还可能重试，不能把 Graph 2 次等同总请求次数。 |
| C2 非法 Tool 参数 | PASS：缺失/额外身份字段在 JSON Schema 边界报 `tool_arguments_invalid`，handler 未调用；模型不能通过参数覆盖后端租户/用户。 |
| C3 工具超时 | PARTIAL：短超时 `asyncio.wait_for` 测试触发 `TimeoutError`，协作式 handler 被取消且 0 次副作用；外部服务收到请求后是否已写入仍不确定，不能只靠取消保证无副作用。 |
| C4 订单不存在/越权/DB 异常 | PARTIAL：真实跨用户/租户查询 `found=false`；退款写边界无归属订单抛 `order_not_found` 且 0 次工单创建。数据库断连的 HTTP/Trace 降级尚未注入。 |
| C5 RAG 失败/空结果 | PARTIAL：已有 `tests/test_hybrid_rag.py` 覆盖一路失败降级、两路失败抛错、实时订单跳过 RAG；没有在真实 API 上注入 Qdrant 故障，也没有把空结果回答的忠实性量化。 |
| C6 重复申请/确认 | PARTIAL：P0 和本轮真实 JWT 测试中重复批准 409、对应工单数 1；同一 confirmation ID 已落入 `SupportTicket.idempotency_key` 唯一键，单元测试重复取回已有工单且不同订单复用同 ID 得 409。跨会话、不同确认 ID 对同一订单的重复自然语言申请尚未验证/约束。 |
| C7 并发确认 | PASS（领取边界）：真实本地 MySQL 两个 session 并发 `claim_for_approval`，结果 `[False, True]`，测试确认单状态 `approved`；该测试不调用售后工具，故只能证明原子领取，不能替代并发完整 HTTP 写入验收。 |
| C8 写入后失败/跨库一致性 | OPEN RISK：Mock 故障证明 Graph resume 返回后若 MySQL commit 失败，门面 rollback，但 PostgreSQL 最新 checkpoint 可能已完成而 MySQL 退款工单/确认状态未提交。另一方向，`create_pending_action` 在 interrupt 前提交 MySQL；随后 PostgreSQL checkpoint 失败，可留下未绑定有效中断点的 pending 记录。当前正常退款工单提交发生在 `graph_runtime.resume()` 返回**之后**，因此“工单 MySQL 已提交但本次 Graph checkpoint 未完成”不是此路径的通常顺序；不能把专家假设直接当作已复现事实。未实现跨库自动对账/补偿。 |
| C9 重启/Checkpoint | PARTIAL：P0 报告已实测 pending → 仅重启 app → PostgreSQL 恢复 → 批准；本轮新源码在一次性 TestClient/真实服务上完成批准，并重启常驻 app 后 ready=200。未在本轮再次把未决 confirmation 跨重启后执行。 |
| C10 日志/Trace 脱敏 | PARTIAL：合成 Bearer 内容在旧 `OpenAICompatibleLLMClient.chat` 的错误和日志中复现泄露；修复后普通/流式模型错误均只记录异常类型并返回通用错误，回归通过。尚未证明所有组件安全：RAG 降级和部分工具 Trace 仍使用 `str(exc)`，可能包含外部异常敏感内容；禁止把本轮说成全链路脱敏验收。 |

受控故障测试均用 Mock/短超时，无真实模型服务破坏、数据库断网或容器杀进程。C8 的两个测试验证事务调用顺序及回滚边界，并非真实跨库 crash/recovery 压测。

## 真实业务数据交叉对照

新订单由 `scripts/seed_p1_security_data.py` 先全局查重再插入；未更新既有订单。`202610210103` 属于 `p1-tenant-a/p1-customer-a`：真实 JWT + LLM 测试批准并重试之后，`scripts/verify_p1_refund.py` 只读查到确认单 `5f26540b-811f-42db-a0c1-f8992f1288c6` 为 `executed`，thread `84b9a785-6636-4112-b6ee-0153ba00f868`；工单 `578195ed-e243-4e62-b122-15813acc8295` 为 `open`，数量 **1**，唯一键 `refund:5f26540b-811f-42db-a0c1-f8992f1288c6`。对照 `p1-tenant-b/p1-customer-b` 的 `202610210104` 工单与确认单均为 **0**。这是售后申请工单，不是付款退款。

## 本轮真实修改与已有能力

P0 的 LangGraph、HIL、Checkpoint、Redis 锁、订单查询和基础测试是此前已有/上一阶段成果，不算本轮从零开发。本轮修复：

1. Graph 快照越权：`routes_graph.get_graph_thread` 原以已脱敏 state 的 `request` 判归属，取不到时未校验。改用 `run_id → AgentRunRepository.get_run → authorize_identity`；`tests/test_graph_thread_authorization.py` 先复现 200，再验证外租户 403/缺 owner 404。
2. 退款工单无确认级唯一键：`after_sales_tools.create_refund_case → BusinessGateway.create_refund_case → TicketRepository` 原未传 `confirmation_id`，唯一列长期为空。现在传可信后端上下文 ID，先查已有工单，校验租户/用户/订单，插入时写 `refund:<confirmation_id>`；`tests/test_refund_write_idempotency.py` 先失败再通过。数据库唯一约束阻止同一键产生第二条，但独立跨库事务仍有窗口。
3. 模型异常回显：`OpenAICompatibleLLMClient.chat/stream_chat` 原把底层异常 `str(exc)` 写入日志/HTTP 错误。改为异常类别日志和通用 ExternalServiceError；`tests/test_p1_fault_boundaries.py` 用合成 Bearer 文本先复现，再验证不泄露。

新增 `tests/test_p1_cross_store_windows.py`、`tests/test_p1_confirmation_concurrency_db.py`、JWT 集成测试及合成数据/只读核对脚本；未更改 `.env`、密钥或原有 `docker-compose.yml`、`.dockerignore`、`.serena/`。后面三者仍为用户原有未提交状态。没有 push。

## 复现与下一步

默认回归（Ubuntu-22.04 WSL，确保当前本地演示服务可用）：

```bash
docker compose run --rm --no-deps -T -e P0_DB_TEST=1 \
  -v "$PWD/src:/app/src:ro" -v "$PWD/scripts:/app/scripts:ro" \
  -v "$PWD/tests:/app/tests:ro" -v "$PWD/pyproject.toml:/app/pyproject.toml:ro" \
  app python -m pytest -q /app/tests
```

一次性 JWT 写测试需**全新未使用**的合成订单，每次临时生成密钥，不得复用 `202610210103`；`tests/test_p1_auth_live.py` 的门控说明和种子脚本是执行入口。数据库只读对照：`python scripts/verify_p1_refund.py <tenant_id> <user_id> <order_id>`。不要在终端或报告输出 JWT、`.env`、模型 Key。默认回归不会重复写退款工单。

P2 只建议、不执行：先清洗 30–50 条固定订单/退款/RAG/故障场景，定义任务成功率、工具选择准确率、RAG Recall@K/MRR 与回答忠实性，再记录 P50/P95 延迟；最后在干净 Docker 环境重新构建和部署验收。P1 残留最高风险是跨库状态对账、跨会话同订单重复申请策略、全链路异常脱敏和常驻服务启用鉴权后的部署验证。
