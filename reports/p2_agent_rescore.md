# P2 Agent 端到端评测（2026-10-21）

## 范围和分母

固定选中 2 例；已尝试 2，确认通过 0，失败 1，待人工语义复核 1，未执行 0。
保守确认成功率：0.0（通过数 / 已尝试数；待复核也保留在分母）。

未执行案例不进入已尝试分母；失败、超时和待复核不得静默剔除。回复文本正确但无工具/DB 证据不判成功。

## 环境

Git `35bbb13c8f9f1f17b69ca11d0daa8460e537447e`；模型 `gpt-5.6-terra`；配置检索模式 `hybrid`；OpenSearch `False`；串行 HTTP 请求 4。上游 LLM 调用次数和中转站费用未由此推断。

## 逐例

| Case | 类别 | 状态 | 失败/待检原因 | 请求数 |
|---|---|---|---|---:|
| C02 | conversation | fail | graph_status_error | 2 |
| C06 | conversation | needs_review | manual_semantic_review_pending | 2 |

## 失效分类

`{"graph_status_error": 1}`

## 局限

知识问答的语义正确性与依据忠实性需人工复核；安全用例必须在独立开启 JWT 的环境执行；Mock 故障不能冒充真实服务故障。当前结果不是生产 SLA。
