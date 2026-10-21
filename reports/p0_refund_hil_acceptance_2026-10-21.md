# P0 退款人工确认闭环：本地实测记录（2026-10-21）

范围：仅 `default/p0_acceptance` 的本地模拟订单；“退款”均指**退款申请售后工单**，未执行支付退款。未输出或保存 `.env` / API Key。原有 `docker-compose.yml` 修改、`.dockerignore` 和 `.serena/` 均未覆盖。执行分支为 `codex/refund-hil-p0`，起点 HEAD `c1db4a4f363cb72c4b31ef739c27142c4a26c429`。

## 环境与基线

- Ubuntu-22.04 WSL，现有 Python 3.11 app 镜像；app、MySQL、PostgreSQL Checkpoint、Redis、Qdrant、Ollama 六个容器运行。`/health/live` 与 `/health/ready` 正常；另以 MySQL `SELECT 1`、PostgreSQL `pg_isready`、Redis `PING`、Qdrant `/healthz` 验证连通性。`ready=ok` 不代替数据库连通性检查。
- 运行配置：`GRAPH_CHECKPOINTER=postgres`、`MCP_AFTER_SALES_ENABLED=false`、`SECURITY_ENABLED=false`、`REQUEST_LOCK_ENABLED=true`。这是本地业务闭环验证，**不是鉴权、租户隔离或公开生产部署验收**。
- 原测试基线：87 passed、0 failed、1 warning。最终在同一现有镜像、挂载本次源码与测试运行：见文末测试命令。
- 因全量 `docker compose build app` 下载依赖过慢，已中断，未替换原镜像。使用 `docker-compose.p0.yml` 只读挂载源码/脚本加载本次修复。**干净镜像重建尚未验证**。

## 六项验收

| 项目 | 结果 | 交叉证据 |
| --- | --- | --- |
| 两轮会话连续性 | PASS | 同一 `conversation_id=e772e2a6-98b2-4acf-9005-fb85994324b8`、`thread_id=2e596732-b83b-49da-957f-19200993e60f`；第二轮“这个订单能退款吗”被改写为订单 `202610210001`，真实 LLM 调用 `query_order_status` 得到该订单。第三轮仅说“这个订单”提交申请，Pending Action 参数仍为 `202610210001`；拒绝后对应工单数 0。第三轮 run `51f82aeb-fb77-4b2a-84f3-91b2b3887746`，confirmation `8448806a-2572-4848-9426-fcda00fa5f24`。 |
| Pending Action 与 interrupt | PASS | 订单 `202610210001` 的另一独立确认 `9639b195-b8f3-4474-8a2c-7360dafce54f`，run `c0481218-642f-4c08-af38-68747abc603f`；待确认时图 `next_nodes=["await_confirmation"]`，PostgreSQL 对应线程有 9 条 checkpoint，MySQL 工单数 0。 |
| 拒绝不写入 | PASS | 上述确认变为 `rejected`，run trace `apply_confirmation:rejected`，图终态 `completed`、`next_nodes=[]`，订单 `202610210001` 工单数始终 0。连续会话的第二次拒绝亦为 0。 |
| 批准受控写入 | PASS（经修复） | 订单 `202610210002`：确认 `b7e0ed43-6d02-43cc-a12b-bdad63fd4f88`，run `61e5d9a6-a584-4bb4-9448-f420937e9b3a`，thread `33c22f9f-cc44-402f-9657-5b298965e1e7`；确认前工单 0，批准后确认单 `executed`、run `success`、MySQL 唯一工单 `8dd7b4b3-e8ca-4e99-8d88-90d3bee70ada`，数量 1。初次批准曾 500，原因与修复见下。 |
| 跨进程恢复 | PASS | 批准单在 `docker compose ... restart app` 前，图快照处于 `await_confirmation`，PostgreSQL 对应 thread 有 10 条 checkpoint，工单 0；仅重启 app，之后确认单仍为 `pending`、图仍等待，再批准并完成。拒绝单也曾在重启后继续恢复。最终 PostgreSQL 该批准 thread 有 15 条 checkpoint、图 `next_nodes=[]`。 |
| 重复批准防护 | PASS（经修复） | 原行为是 HTTP 200 重放已完成图，虽工单仍 1；增加确认单状态门禁后，对同一 ID 再批准实际返回 HTTP **409**、`confirmation_not_pending`，工单仍 **1**。这只证明此路径无二次写入，不代表跨所有故障窗口的全局“恰好一次”。 |

修复后另用独立订单 `202610210003` 实测完整批准与最终答复：待确认前工单 0；confirmation `fa911249-e34c-41be-b7a4-fc1514cf5b9a`，run `a7633533-9caa-427c-82d9-7221a68c2f48`，thread `87e8f652-cdae-474f-9a7f-892cc7e31123`；批准 HTTP 200，工单 `7f2b6ac5-4a91-4e53-ba45-91101295e45a`、数量 1；回复明确订单已发货及“退款申请已提交”，返回 `create_refund_case` 的真实 `ticket_id`，Trace 为 `apply_confirmation:approved → finalize:success → persist:success`，`wait_seconds=20.29`。`202610210004` 是种子脚本一同生成但未使用的备用模拟订单，工单数 0。

数据库最终核对：`202610210001=0`、`202610210002=1`、`202610210003=1`、`202610210004=0`（以上为同租户、同测试用户、`category=refund`、元数据订单号匹配的工单）。三个主要 thread 的 PostgreSQL checkpoint 数分别为 12、15、15；图最终均为 `completed`、无下一节点。Graph 状态接口的 `interrupts` 字段仍包含历史中断记录，不能把它当成仍在等待。

## 实际发现和最小修复

1. 初次创建确认单因 MySQL server default 列被 async ORM 延迟加载而出现 `MissingGreenlet`；`PendingActionRepository.create` 在 flush 后显式 refresh。普通“提交退款申请”原本走 direct-tool 并只以文本要求确认，`QuestionRouter` 增加明确的退款提交意图门禁，实际进入 Planner/HIL。
2. MySQL `DATETIME` 丢失时区，确认单查询和批准条件更新出现 naive/aware 时间比较错误；`ConfirmationService._is_expired` 按 UTC 解释旧记录，`claim_for_approval` 禁用 Python 会话同步求值，新的确认单显式以 UTC 写入创建时间，消除负等待时长。
3. 本地退款写入原无订单归属检查；`BusinessGateway.create_refund_case` 在 `TicketRepository.create` 前按 tenant/user/order 查询，不存在或不属于该用户则 404；并防止模型提供的 `metadata.order_id` 覆盖已校验的订单号。这是业务写入边界保护，**不是完整鉴权验收**。
4. 已执行确认单原可继续 `Command(resume=...)` 并返回旧 HTTP 200；Agent 门面在恢复前检查 `pending`，重复提交改为 409。批准后 `final_answer` 原沿用确认提示，且计划执行的写入结果未出现在 `tool_results`；`apply_confirmation` 现清空旧提示、保留批准结果，`finalize` 生成新的最终答复。

退款申请经 `QuestionRouter → Planner → query_order_status → create_pending_action → await_confirmation/interrupt → Command(resume) → apply_confirmation → BusinessGateway → TicketRepository → finalize/persist`。订单查询轮确有真实模型 Tool Calling；退款轮确有 Planner 路径及真实模型最终生成。当前 per-run Trace 没有明确标注 Planner 计划是模型生成还是规则 fallback，故**不把每次计划都称作模型自主规划**。

## 复现命令（Ubuntu-22.04 WSL，先确认本地演示环境）

```bash
cd /mnt/d/YJSXueXi/learning_source/models/enterprise-customer-service-agent-v2
git status --short
docker compose --profile durable --profile embedding ps
docker compose -f docker-compose.yml -f docker-compose.p0.yml up -d --no-deps --no-build --force-recreate app
docker compose -f docker-compose.yml -f docker-compose.p0.yml run --rm --no-deps -T app python scripts/seed_refund_acceptance_data.py <全新拒绝订单号> <全新批准订单号>
docker compose run --rm --no-deps -T -e P0_DB_TEST=1 -v "$PWD/src:/app/src:ro" -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/tests:/app/tests:ro" -v "$PWD/pyproject.toml:/app/pyproject.toml:ro" app python -m pytest -q /app/tests
```

订单号必须为未占用的 8–24 位数字；种子脚本会先检查两号全局未使用，绝不更新旧订单。API 路径：`POST /api/v1/chat`、`GET /api/v1/graph/threads/{thread_id}`、`GET /api/v1/confirmations/{confirmation_id}`、`POST /api/v1/confirmations/{confirmation_id}/approve|reject`、`GET /api/v1/agent-runs/{run_id}`。请求体用本地演示身份 `tenant_id=default,user_id=p0_acceptance`；第二轮务必带回第一轮响应的 **conversation_id 与 thread_id**。不要在报告或命令输出中展示 `.env`、Authorization 或模型 Key。

最终测试：**99 passed、0 failed、0 skipped、1 warning**（passlib 依赖的 Python `crypt` 弃用警告）。

## 剩余风险与下一阶段优先级

1. `SECURITY_ENABLED=false`：尚未验证真实登录态、身份归属与跨租户隔离；当前身份可由请求字段提供。后续应先开启鉴权并做跨用户/租户故障用例。
2. 本地数据库的单确认防重已验，但 PostgreSQL Checkpoint 与 MySQL 业务写入不是同一事务；若未来启用外部 MCP 写入，需要独立业务幂等键与故障窗口恢复测试，不能宣称全局恰好一次。
3. 干净 Docker 镜像重建与新环境一键部署仍未验。之后再做故障注入与 30–50 条固定 Agent 业务集，记录实际成功率和延迟；MCP、Hybrid RAG 继续暂缓。
