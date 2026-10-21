# P2 Agent 端到端评测与量化分析（2026-10-21）

## 范围与证据边界

固定用例 40；已尝试 40，确定通过 24，失败 9，待人工复核 7，未执行 0。保守确认成功率 0.6，分母包含待复核。
这不是单一的 40 条真实模型成功率：安全用例在独立 JWT TestClient 运行，故障注入含 Mock 单测；请按下面的来源分开解释。

常驻服务真实网络部分单列：34 例，确定通过 18，失败 9，待复核 7；这些场景也并非每例都调用模型（含参数校验与 404）。

Git `35bbb13c8f9f1f17b69ca11d0daa8460e537447e`；模型 `gpt-5.6-terra`；固定种子 `20261021`；常驻服务 `SECURITY_ENABLED=False`；配置检索 `hybrid`，OpenSearch `False`；真实 HTTP 串行执行。
真实网络执行器 HTTP 请求 55 次；这不是上游 LLM 请求数，中转站费用不可由本报告推断。

另有 C02/C06 重跑 4 次 HTTP、已落盘的 pilot 3 次 HTTP，以及首次因容器缺 git 导致报告未落盘的 pilot 5 次 HTTP；这些开发/诊断请求不计入固定 40 例的成功率。

C02/C06 因首版评测器把中间澄清误判为图错误而按修正判据独立重跑；原结果保留在 `p2_agent_results.json`，重跑证据在 `p2_agent_rescore_results.json`。C02 重跑仍失败，C06 改为待人工复核；不可把重跑抹成首次成功。

## 分组结果

| 类别 | 通过 | 失败 | 待人工复核 | 未执行 |
|---|---:|---:|---:|---:|
| conversation | 2 | 2 | 2 | 0 |
| fault | 6 | 0 | 0 | 0 |
| isolation | 4 | 0 | 0 | 0 |
| knowledge | 0 | 3 | 5 | 0 |
| orders | 8 | 0 | 0 | 0 |
| refund | 4 | 4 | 0 | 0 |

## 工具与数据正确性

明确标注期望工具的已尝试场景 14 例，其中执行结果中可见期望工具且 `ok=true` 的 12 例。此值是工具执行可见率，不等同参数完全准确率；错误参数另以失败分类和逐例证据判断。
退款场景只有在 Pending Action、Graph 中断、批准/拒绝状态及 MySQL 工单数量一致时才判通过；‘提交退款’只意味着申请工单，不代表支付退款。

退款失败的主要现象是 R03/R05/R07/R08 仅查订单或进入澄清，未创建 Pending Action。原因尚需针对规划/意图进一步诊断，不把它包装成已修复。

## 执行来源

`{"chat": 23, "refund": 8, "isolated_jwt_http": 3, "mock_tool_schema": 1, "http_negative": 3, "mock_regression": 2}`

## 失败分布

`{"confirmation_not_created": 4, "graph_status_error": 1, "retrieval_miss": 3, "tool_selection_error": 1}`

知识类 3 例来源未命中，多轮类 1 例目标工具未出现、1 例仍需澄清；退款类 4 例未触发确认。未发现本轮退款失败例的意外工单写入。

## 逐例可复核索引

| Case | 状态 | 环境/模式 | 原因 | run_id | confirmation_id | DB 前→后 |
|---|---|---|---|---|---|---|
| K01 | needs_review | chat | manual_semantic_review_pending | 6ae13dc1-cb07-4ec1-a44e-edf0dad5f709 | — | —→— |
| K02 | fail | chat | retrieval_miss | 506f4192-229c-4d87-a30d-527311b1bc8d | — | —→— |
| K03 | fail | chat | retrieval_miss | aa0b305f-e7e8-400b-959c-4956cf79326d | — | —→— |
| K04 | needs_review | chat | manual_semantic_review_pending | 02fa224f-30c9-4cf5-b876-9e54687e4845 | — | —→— |
| K05 | needs_review | chat | manual_semantic_review_pending | 6c65a446-6268-40c4-a0bb-ab81595a14f9 | — | —→— |
| K06 | needs_review | chat | manual_semantic_review_pending | c7b439e5-2a32-48f9-8416-4c209925d323 | — | —→— |
| K07 | fail | chat | retrieval_miss | bfbe968b-b4fd-47b7-9e88-972ce1cb3186 | — | —→— |
| K08 | needs_review | chat | manual_semantic_review_pending | dc34f7f5-2ac4-4aa0-8e8c-9ab20dc8e09e | — | —→— |
| O01 | pass | chat | — | e9a07217-8d4b-4c7b-b952-7c5cf44bf7ad | — | 0→0 |
| O02 | pass | chat | — | 3e5b6703-59a0-4278-84e2-a2289dfaf7d0 | — | 0→0 |
| O03 | pass | chat | — | 9ffdf6cc-d589-421d-a4cb-d7750a3274c8 | — | 0→0 |
| O04 | pass | chat | — | 88b68285-1dac-4bae-be3b-8d923f902082 | — | 0→0 |
| O05 | pass | chat | — | 66f761d2-f2ae-4737-ac5a-997a13971a5a | — | 0→0 |
| O06 | pass | chat | — | 362c129e-a569-4001-a013-c5aff0ab162f | — | 0→0 |
| O07 | pass | chat | — | 9986b3fe-5262-4d2e-80a9-8b7af499153d | — | 0→0 |
| O08 | pass | chat | — | 1113faa2-d1a8-4a90-883a-de20815262de | — | 0→0 |
| C01 | pass | chat | — | bf7d7291-717d-4578-bf17-e1b02ceeba7e | — | 0→0 |
| C02 | fail | chat | graph_status_error | cf882d99-f989-4b39-b3de-0ef30fdb4981 | — | 0→0 |
| C03 | needs_review | chat | manual_semantic_review_pending | 1123a90b-09fd-450e-9128-882f06cd69be | — | 0→0 |
| C04 | pass | chat | — | 2592a0a1-f2ee-4394-96c8-4507cb3811c8 | — | 0→0 |
| C05 | fail | chat | tool_selection_error | d91a1d86-9669-49f6-bd7a-dc61f5c6c1e6 | — | 0→0 |
| C06 | needs_review | chat | manual_semantic_review_pending | be2d405a-36dc-4d20-9fd3-6de68d9f5fdc | — | —→— |
| R01 | pass | refund | — | cef8051b-9dd0-4c1d-8953-edd402a17f6c | 454deb26-6f52-4e8a-a647-9cace4cf8ea2 | 0→0 |
| R02 | pass | refund | — | bc228ee8-8fd5-4faf-862e-a456d18454fe | 733faab7-da99-444a-a415-7abe64c08894 | 0→1 |
| R03 | fail | refund | confirmation_not_created | f89acf75-37b1-4981-96c6-48a75174c597 | — | 0→— |
| R04 | pass | refund | — | 4d127159-2f15-4f09-9d2c-3da90cccae7c | 368a6b14-65fc-4b31-8fa6-d3fe9ed56157 | 0→1 |
| R05 | fail | refund | confirmation_not_created | e52dd713-eaf7-416f-9999-80f4303ea6c7 | — | 0→— |
| R06 | pass | refund | — | 0bf2f225-73d7-4f52-b30d-2cfaa4646030 | f6b8d42b-ceb3-49ca-ab6f-c051f7f3f352 | 0→1 |
| R07 | fail | refund | confirmation_not_created | 392fe8fa-f345-4c46-bfb9-cb19cf5d0c64 | — | 0→— |
| R08 | fail | refund | confirmation_not_created | 81f0e98b-8b2f-4379-9b78-5c9fbabdb873 | — | 0→— |
| I01 | pass | isolated_jwt_http | — | — | — | —→— |
| I02 | pass | isolated_jwt_http | — | fc7ea260-197c-458d-90ea-105b65d26110 | — | —→— |
| I03 | pass | isolated_jwt_http | — | — | — | —→— |
| I04 | pass | mock_tool_schema | — | — | — | —→— |
| F01 | pass | http_negative | — | — | — | —→— |
| F02 | pass | http_negative | — | — | — | —→— |
| F03 | pass | chat | — | da9c1c88-8d46-41b9-b06f-040aabd79b89 | — | —→— |
| F04 | pass | http_negative | — | — | — | —→— |
| F05 | pass | mock_regression | — | — | — | —→— |
| F06 | pass | mock_regression | — | — | — | —→— |

## 退款 MySQL 只读复核

| Case | 退款申请工单数 | 确认单状态 |
|---|---:|---|
| R01 | 0 | rejected |
| R02 | 1 | executed |
| R03 | 0 | 无 |
| R04 | 1 | executed |
| R05 | 0 | 无 |
| R06 | 1 | executed |
| R07 | 0 | 无 |
| R08 | 0 | 无 |

## 持久化 Trace 交叉核对

按本次结果中的 run_id 只读获取 44/44 条 Agent Run；脱敏证据见 `p2_trace_evidence.json`，仅保留步骤状态、工具名、found 布尔值和合成订单号，不保存自由文本载荷。
例如 O01 自有订单的 `query_order_status.found=true`，I02 跨用户查同一合成订单的 `found=false`；这两项不靠聊天文案判断。

### 知识失败的上游路由证据

| Case | 路由来源 | 允许文档类型 | 检索块数 |
|---|---|---|---:|
| K02 | knowledge | faq, risk, sop | 5 |
| K03 | realtime_tool | — | 0 |
| K07 | realtime_tool | — | 0 |

K03/K07 被规则路由到实时工具而未检索；K02 的文档类型过滤不含目标政策类。它们是路由/过滤失误，不可全部算作 embedding 召回问题。


## Dense RAG 单独基线

有效知识 18 题：Hit@1=0.6111，Hit@3=0.7222，Hit@5=0.7222，MRR=0.6667。详见 `p2_rag_evaluation.md`；回答忠实性未人工核验，不报分。

实际为 Dense；旧题集包含过期来源，分数不可直接对比。


## 本轮新增与遗留风险

原项目已具有 FastAPI/LangGraph/HIL/Checkpoint/RAG/业务工具；本轮新增固定用例、执行器、P2 合成数据、Dense 检索与延迟统计，不将旧实现写为本轮原创。
本报告未验证跨 MySQL/PostgreSQL 全局 exactly-once、常驻服务开启鉴权、真实外部服务故障窗口或公开生产部署。语义待人工复核不算已确认成功。模型规划与规则回退未逐例独立确认，不能把所有工具调用称为模型自主选择。

P3 干净部署与冻结的前提：解释并修复影响主链路的失败、补人工回答忠实性核验、明确常驻 JWT 配置与跨库一致性限制；本轮不自行进入 P3。
