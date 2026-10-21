# P2 Dense RAG 检索评测（2026-10-21）

租户 `p2-evaluation`；配置 `hybrid`，实际 `dense`；OpenSearch `False`；top_k=5。

有效知识题 n=18：Hit@1=0.6111，Hit@3=0.7222，Hit@5=0.7222，MRR=0.6667。

旧题集 Hit@5=0.65/MRR=0.60 含已过期来源，评测集不同，不能把差值解释为模型优化收益。

| ID | 类别 | 相关来源排名 | Top-K 来源 |
|---|---|---:|---|
| exact-policy-code | valid | 2 | policies/质量问题退换货政策.md, policies/七天无理由退货政策.md, matrices/售后赔付标准矩阵.md, sop/投诉升级与转人工流程.md, policies/七天无理由退货政策.md |
| semantic-return | valid | 2 | manuals/智能耳机使用与保修手册.md, matrices/商品类目退换限制矩阵.md, policies/七天无理由退货政策.md, manuals/智能耳机使用与保修手册.md, troubleshooting/智能耳机故障排查.md |
| refund-arrival | valid | 1 | faq/退款到账常见问题.md, faq/退款到账常见问题.md, policies/七天无理由退货政策.md, sop/退款申请处理流程.md, risk/异常退款与凭证规则.md |
| payment-account | valid | 1 | faq/退款到账常见问题.md, sop/退款申请处理流程.md, risk/异常退款与凭证规则.md, faq/退款到账常见问题.md, sop/退款申请处理流程.md |
| logistics-code | expired | — | risk/异常退款与凭证规则.md, faq/退款到账常见问题.md, sla/企业客户响应时效.md, faq/退款到账常见问题.md, risk/异常退款与凭证规则.md |
| delivered-missing | valid | 1 | faq/订单与物流常见问题.md, sop/退款申请处理流程.md, policies/七天无理由退货政策.md, policies/七天无理由退货政策.md, sop/退款申请处理流程.md |
| defect-evidence | valid | — | risk/异常退款与凭证规则.md, risk/异常退款与凭证规则.md, sop/退款申请处理流程.md, risk/异常退款与凭证规则.md, sop/投诉升级与转人工流程.md |
| refund-sop | valid | — | — |
| handoff | valid | — | — |
| earbud-pairing | valid | 1 | manuals/智能耳机使用与保修手册.md, troubleshooting/智能耳机故障排查.md, troubleshooting/智能耳机故障排查.md, manuals/智能耳机使用与保修手册.md, troubleshooting/智能耳机故障排查.md |
| battery-safety | valid | 1 | troubleshooting/充电与电源故障排查.md, troubleshooting/充电与电源故障排查.md, troubleshooting/充电与电源故障排查.md, manuals/智能耳机使用与保修手册.md, troubleshooting/智能耳机故障排查.md |
| appliance-smoke | valid | 1 | manuals/小家电安装与保养手册.md, manuals/小家电安装与保养手册.md, manuals/小家电安装与保养手册.md, troubleshooting/充电与电源故障排查.md, troubleshooting/充电与电源故障排查.md |
| member-rights | valid | 1 | benefits/会员售后权益.md, benefits/会员售后权益.md, risk/异常退款与凭证规则.md, benefits/企业客户服务权益.md, benefits/企业客户服务权益.md |
| enterprise-contract | valid | — | matrices/售后赔付标准矩阵.md, sop/投诉升级与转人工流程.md, matrices/商品类目退换限制矩阵.md, matrices/售后赔付标准矩阵.md, sop/投诉升级与转人工流程.md |
| price-code | expired | — | policies/七天无理由退货政策.md, benefits/会员售后权益.md, matrices/商品类目退换限制矩阵.md, policies/七天无理由退货政策.md, policies/七天无理由退货政策.md |
| compensation | valid | 1 | matrices/售后赔付标准矩阵.md, risk/异常退款与凭证规则.md, matrices/售后赔付标准矩阵.md, sop/投诉升级与转人工流程.md, policies/七天无理由退货政策.md |
| risk-evidence | valid | 1 | risk/异常退款与凭证规则.md, sop/退款申请处理流程.md, risk/异常退款与凭证规则.md, sop/退款申请处理流程.md, sop/退款申请处理流程.md |
| security-secret | valid | 1 | risk/账户与支付安全提醒.md, risk/账户与支付安全提醒.md, risk/账户与支付安全提醒.md, risk/异常退款与凭证规则.md, risk/异常退款与凭证规则.md |
| merchant-evidence | valid | 1 | merchant/商家履约与举证规则.md, merchant/商家履约与举证规则.md, merchant/商家履约与举证规则.md, merchant/平台介入处理规则.md, sop/退款申请处理流程.md |
| p1-sla | valid | — | sop/投诉升级与转人工流程.md, sop/投诉升级与转人工流程.md, manuals/小家电安装与保养手册.md, sop/投诉升级与转人工流程.md, risk/异常退款与凭证规则.md |
| realtime-order | realtime | — | — |
| no-grounding | no_evidence | — | faq/订单与物流常见问题.md, sla/重大故障升级机制.md |

过期题只检查过期来源不应露出；实时题只检查检索跳过；无依据题的最终回答安全性未由检索排名证明。回答事实准确性/忠实性未自动评分，需人工核对。
