# P2 Agent 端到端评测（2026-10-21）

## 范围和分母

固定选中 40 例；已尝试 34，确认通过 22，失败 2，待人工语义复核 10，未执行 6。
保守确认成功率：0.6471（通过数 / 已尝试数；待复核也保留在分母）。

未执行案例不进入已尝试分母；失败、超时和待复核不得静默剔除。回复文本正确但无工具/DB 证据不判成功。

## 环境

Git `unavailable`；模型 `gpt-5.6-terra`；配置检索模式 `hybrid`；OpenSearch `False`；串行 HTTP 请求 65。上游 LLM 调用次数和中转站费用未由此推断。

## 逐例

| Case | 类别 | 状态 | 失败/待检原因 | 请求数 |
|---|---|---|---|---:|
| K01 | knowledge | needs_review | manual_semantic_review_pending | 1 |
| K02 | knowledge | needs_review | manual_semantic_review_pending | 1 |
| K03 | knowledge | needs_review | manual_semantic_review_pending | 1 |
| K04 | knowledge | needs_review | manual_semantic_review_pending | 1 |
| K05 | knowledge | needs_review | manual_semantic_review_pending | 1 |
| K06 | knowledge | needs_review | manual_semantic_review_pending | 1 |
| K07 | knowledge | needs_review | manual_semantic_review_pending | 1 |
| K08 | knowledge | needs_review | manual_semantic_review_pending | 1 |
| O01 | orders | pass | — | 1 |
| O02 | orders | pass | — | 1 |
| O03 | orders | pass | — | 1 |
| O04 | orders | pass | — | 1 |
| O05 | orders | pass | — | 1 |
| O06 | orders | pass | — | 1 |
| O07 | orders | pass | — | 1 |
| O08 | orders | pass | — | 1 |
| C01 | conversation | pass | — | 2 |
| C02 | conversation | pass | — | 2 |
| C03 | conversation | needs_review | manual_semantic_review_pending | 2 |
| C04 | conversation | pass | — | 2 |
| C05 | conversation | fail | tool_selection_error | 2 |
| C06 | conversation | needs_review | manual_semantic_review_pending | 2 |
| R01 | refund | pass | — | 4 |
| R02 | refund | pass | — | 4 |
| R03 | refund | pass | — | 4 |
| R04 | refund | pass | — | 5 |
| R05 | refund | fail | confirmation_not_created | 2 |
| R06 | refund | pass | — | 5 |
| R07 | refund | pass | — | 5 |
| R08 | refund | pass | — | 4 |
| I01 | isolation | not_run | requires_isolated_security_or_mock_harness | 0 |
| I02 | isolation | not_run | requires_isolated_security_or_mock_harness | 0 |
| I03 | isolation | not_run | requires_isolated_security_or_mock_harness | 0 |
| I04 | isolation | not_run | requires_isolated_security_or_mock_harness | 0 |
| F01 | fault | pass | — | 1 |
| F02 | fault | pass | — | 1 |
| F03 | fault | pass | — | 1 |
| F04 | fault | pass | — | 1 |
| F05 | fault | not_run | requires_isolated_security_or_mock_harness | 0 |
| F06 | fault | not_run | requires_isolated_security_or_mock_harness | 0 |

## 失效分类

`{"confirmation_not_created": 1, "tool_selection_error": 1}`

## 局限

知识问答的语义正确性与依据忠实性需人工复核；安全用例必须在独立开启 JWT 的环境执行；Mock 故障不能冒充真实服务故障。当前结果不是生产 SLA。
