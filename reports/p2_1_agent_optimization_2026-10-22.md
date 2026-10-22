# P2.1 Agent 主链路失败分析与定向优化（完成）

## 证据冻结与边界

- 起点：`codex/refund-hil-p0`，HEAD `80b4c17af7def2d8103e50426bef4b57a1b78bc3`。
- 用户原有未提交：`M docker-compose.yml`、`?? .dockerignore`、`?? .serena/`，本轮不覆盖。
- 原始固定集 40 例：24 pass、9 fail、7 needs_review。真实网络 34 例（18 pass、9 fail、7 needs_review）；隔离 JWT 与 Mock 另计。原 P2 报告和结果保留原路径，不覆盖。
- 原始工单 R02、R04、R06 已各有一条退款**申请**工单。原执行器在退款工单初始数量非零时返回 `fixture_already_has_refund_ticket`，所以复测不能直接复用这批订单号；将使用新的唯一合成订单，并保留 case ID、提问模板和评分判据。
- 常驻服务演示配置 `SECURITY_ENABLED=false`，OpenSearch/MCP 未启用；不得推断生产鉴权或 Hybrid RAG 已验收。

| 原始文件 | SHA-256 |
|---|---|
| `evals/agent_cases.jsonl` | `A4D88CC00E0AE77DD1865CE026FF8A5C8E185648CE0D7E85768629D381B00E50` |
| `reports/p2_all_results.json` | `92379B62B9B4B2DFC71B1D42BBCF9A34A1D5BE1DF19782A4AF03E646207E0D47` |
| `reports/p2_trace_evidence.json` | `D3C24C9C2BB91724C82B59A083D62F7B917E459CCA949B21C1258B2083F75A33` |
| `reports/p2_refund_db_audit.json` | `49FF03956ED785275A015317A882E120D35DDD51862D3EDB1AD90CDCFEDF5A82` |
| `reports/p2_rag_results.json` | `8D97542071531B6C5A0CA4DFD5ACD868C2871B63B5B717C35F27178B70539CFD` |

原 P2 JSON 刻意不保存回答正文；本轮确认原 PostgreSQL 图快照仍有 `final_answer`、`query_rewrite`、`route_decision`。仅读取本地合成会话的脱敏必要字段做人工判读；不把自由文本响应批量导出到报告。

## 起始定位清单（保留阶段初观察；最终结论见后文）

| Case | 原失败类型 | 阶段初观察到的边界事实 | 阶段初状态 |
|---|---|---|---|
| R03 | confirmation_not_created | `direct_tool`，查订单成功，未进 Planner；答复要求补充退款原因 | 待复核 |
| R05 | confirmation_not_created | 第二轮改写已含正确订单号，但 `needs_clarification=true`、缺“退款原因”，Graph 停在 clarify | 待复核 |
| R07 | confirmation_not_created | `direct_tool`，查订单成功，文本要求用户确认，却没有 Pending Action | 待复核 |
| R08 | confirmation_not_created | `direct_tool`，查订单成功，未生成确认单 | 待复核 |
| K02 | retrieval_miss | 走 knowledge，但过滤仅 `faq,risk,sop`，未包含目标 `policy` | 待复核 |
| K03 | retrieval_miss | 误走 realtime/planner；检索块 0 | 待复核 |
| K07 | retrieval_miss | 误走 realtime/planner；检索块 0 | 待复核 |
| C02 | graph_status_error | 两轮均为 needs_clarification；第二轮改写含历史订单号，却仍标记待确认 | 待复核 |
| C05 | tool_selection_error | 使用 `query_order_status` 而非预期 `query_logistics_status`；图快照的最终答复已包含正确模拟运单号，须区分严格工具判据与用户任务结果 | 待复核 |

以上只是边界事实，不预先把所有失败判成代码缺陷。后续按函数、测试和对照请求补证。

## 七例人工复核：原运行证据上的独立裁定

原 P2 JSON 故意丢弃回答正文；本轮只读查询原 thread 的 PostgreSQL 图快照，核对 `final_answer`、改写/路由和 P2 JSON 中保存的来源/工具，再对照仓库内有效知识原文。旧 JSON 的 `needs_review` 保持不变，不篡改原评分。以下裁定不代表新代码已复测。

| Case | 裁定 | 依据与边界 |
|---|---|---|
| K01 | Pass | 答复的签收次日起 7 天、商品完整、合理拆封、排除类目与质量问题例外，均见 `policies/七天无理由退货政策.md`；该文件位于原 Top-K。 |
| K04 | Pass | 答复的核对地址/代收/承运商证明、仍未找到时发起核查而非直接退款，与原命中的 `faq/订单与物流常见问题.md` 一致。 |
| K05 | Pass（附注） | 明确要求停止充电使用、远离易燃物、不穿刺挤压、转人工，均受 `troubleshooting/充电与电源故障排查.md` 支持；额外的危险升级提醒属于一般安全建议，不作为知识库专属事实或检索得分。 |
| K06 | Pass | “会员不能跳过凭证审核/安全验证”与 `benefits/会员售后权益.md` 一致；没有虚构当前会员等级。 |
| K08 | Pass | 不索取支付密码、短信验证码、CVV、远控权限，以及异常后的官方入口处理，均见 `risk/账户与支付安全提醒.md`。 |
| C03 | Pass | 第二轮只问刚查的订单号，最终答复为原合成订单 `202610219103`；第二轮未执行不相关工具。 |
| C06 | Pass | 两轮均无可核验订单号，最终要求补充订单信息；没有调用订单工具或编造订单状态。重复追问由用户未补充信息导致，与 C02 的已有订单反复追问不同。 |

按该人工判据，原固定集的**事后裁定**为 31 Pass、9 Fail（31/40=77.5%）；原自动报告仍保留 24 Pass、9 Fail、7 待复核及其 60% 保守确认率。这不是新版本的提升数据，也不代表 40 例均为真实模型调用。

## 关键业务判据裁定

`knowledge_base/sop/退款申请处理流程.md` 要求先区分了解政策和真正提交，核验订单；信息不足时先追问，确认前展示退款原因。因此 R05 第二轮已正确解析订单，但缺退款原因而进入 `needs_clarification`，属于保守且符合样例 SOP 的行为，**不是应强行绕过的代码错误**。原固定评分要求立即出现 Pending Action，故 R05 在原口径下仍为 Fail；后续报告会同时列出“原评分失败”和“业务安全裁定”，不修改原标准偷换结果。

R03/R07/R08 的路由却是 `direct_tool`，系统只做订单查询、至多用文字要求确认，没有结构化 Pending Action 或明确的参数澄清状态。新路由回归测试在修改前 3/3 失败，修改后进入 Planner；是否能安全形成 Pending 需用新合成订单的真实 HTTP 再验，不能凭单测宣称端到端完成。

## 最终执行与版本边界

本轮在同一仓库、同一分支、未提交起点 `80b4c17af7def2d8103e50426bef4b57a1b78bc3` 上完成；容器内无法读取 `.git`，所以 runner 元数据写 `git_head=unavailable`，以此处主机侧 HEAD 为准。未改动原 P2 case、结果、Trace 和 RAG 报告。为避免批准过的退款单污染复测，分别给定向跑、中间全量跑、最终全量跑各建立一套同判据的新订单命名空间 `202610229*`、`202610228*`、`202610227*`；脚本每套检查并新增 21 条唯一合成订单，合计新增 63 条本地演示订单，没有更新旧订单。它们是评测副作用，尚未清理，也不应误认成真实用户业务量。

最终固定集为 `evals/agent_cases_p2_1_final_2026-10-22.jsonl`：40 个 case ID、类别、问题模板和评分判据与原集一致，仅将专用订单号映射到 `202610227*`。最终网络结果在 `reports/p2_1_final_network_2026-10-22.json`/`.md`；隔离鉴权、Mock 故障分别在 `reports/p2_1_final_security_2026-10-22.json`、`reports/p2_1_final_faults_2026-10-22.json`。中间全量、定向和 R06 回归保留独立文件，不拿中间较好/较差结果替代最终固定集。

执行配置：真实中转模型名 `gpt-5.6-terra`，Ollama embedding，`retrieval_mode=hybrid` 但 OpenSearch 关闭、实际只用 Dense；PostgreSQL Checkpointer；网络 runner 逐例串行，HTTP 超时 90 秒，预算 100，实际 65 个 HTTP 请求。HTTP 次数不等于上游模型调用次数，也没有可靠的账单金额。本地常驻 API 的 `SECURITY_ENABLED=false`；JWT 只在临时 TestClient 测试环境启用。

### 40 例计数：自动评分与人工复核分列

| 口径 | Pass | Fail | 待语义复核 | 部分正确 | 分母与说明 |
|---|---:|---:|---:|---:|---|
| 原 P2 自动 | 24 | 9 | 7 | — | 40；历史冻结，不覆盖 |
| 原 P2 事后人工 | 31 | 9 | 0 | 0 | 40；旧 7 例有持久化回答可复核 |
| 最终网络自动 | 22 | 2 | 10 | — | 34；另 6 例应由隔离 harness 执行 |
| 最终 JWT/Mock | 6 | 0 | 0 | — | I01–I04 4 例；F05–F06 2 例 |
| 最终合并自动 | 28 | 2 | 10 | — | 40；保守通过率 70.0% |
| 最终人工裁定 | 37 | 2 | 0 | 1 | 40；严格 Pass 率 92.5% |

最终相对原 P2 的严格人工 Pass 率为 `37/40` 对 `31/40`，差 6 例、15 个百分点；这只是同模板、不同合成订单、单次真实模型运行的观察结果，**不是因果归因或统计显著的模型能力提升**。原 P2 网络 34 例为 18 Pass、9 Fail、7 待复核；最终网络为 22 Pass、2 Fail、10 待复核。人工裁定把新 10 例中的 9 例判 Pass，K01 判部分正确且不计 Pass。

最终网络请求延迟：65 请求，均值 5204.77 ms、P50 3879.33 ms、P95 15947.52 ms；原 P2 为 61 请求，均值 5524.68 ms、P50 5813.59 ms、P95 12423.56 ms。请求组合和中转站波动不同，不能据此宣称性能优化；P95 反而变高。鉴权和 Mock 请求不混入网络延迟分母。

### 九个原失败的最终判定

| Case | 根因或争议 | 最终严格状态 | 交叉证据 |
|---|---|---|---|
| R03 | 明确申请被判成 `direct_tool`，只有查询，没有 Pending | Pass | 修复后 Graph 计划 `llm_generated`，Checkpoint 停在 `await_confirmation`；拒绝后 MySQL 工单 0、确认单 `rejected` |
| R05 | 第二轮已识别订单，但缺退款原因及是否签收；原判据要求立即 Pending | Fail（业务安全的澄清） | Graph `needs_clarification`，回答询问原因/签收；DB 0 工单、0 确认单；不绕过样例 SOP 强行创建 |
| R07 | 明确提交申请被判成 `direct_tool` | Pass | `llm_generated` 计划进入确认；拒绝与重复拒绝后 DB 0 工单、确认单 `rejected` |
| R08 | 原仅查订单、未产生结构化确认 | Pass | `llm_generated` 计划，批准后 DB 0→1 退款**申请工单**、确认单 `executed`；不是支付退款 |
| K02 | 改写丢掉“需要哪些”政策意图，过滤未纳入 `policy` | 人工 Pass | 最终 Top-K 含 `policies/质量问题退换货政策.md`；回答要求连续展示故障的视频，未要求敏感凭证 |
| K03 | 到账周期被误判成实时订单请求，0 个知识块 | 人工 Pass | FAQ 命中；回答 3–7 个工作日且声明非实时退款进度 |
| K07 | SOP 步骤题误路由到实时/Planner，0 个知识块 | 人工 Pass | 退款 SOP 命中；回答包含意图区分、订单核验、展示内容、用户确认 |
| C02 | 上下文已有订单 ID，却继续标 `needs_clarification` | Pass | 收窄改写后的澄清标记清理条件；最终同一会话两轮通过，缺号的 C06 仍追问 |
| C05 | LLM 两次选 `query_order_status` 而非预期 `query_logistics_status` | Fail（工具严格判据） | 第二轮正确改写出订单，答复含模拟运单号 `P2202610227105`，但 Trace 工具仍是订单查询；定向跑曾通过、全量两次失败，呈模型选择波动；未改写评分掩盖它 |

最终全量前还发现 R06 的真实问题：用户原句“请为这个订单提交退款申请”，模型改写为“如何提交退款申请”，路由和 Planner 只看改写后咨询句。先失败的回归测试见 `tests/test_question_router.py::test_rewrite_cannot_turn_refund_submission_into_consultation`；修复为原句与改写句共同参与动作门禁后，独立 R06 复测和最终固定集均通过。最终 R06 图计划为 `llm_repaired`，批准后 MySQL 工单 0→1。

### 最终 10 例人工语义裁定

只读调取对应 `thread_id` 的 Graph 最终答复，核对网络 runner 的 `sources`/工具，再与仓库内有效知识原文比对；未把原始自由文本或密钥写入 JSON 评测结果。

| Case | 裁定 | 关键依据 |
|---|---|---|
| K01 | Partial，**不计 Pass** | 命中七天无理由政策，商品排除及质量例外基本正确；但答复只说“规定期限”，未明确样例政策的“签收次日起 7 天”，核心时限不完整 |
| K02 | Pass | 质量问题政策在来源中；回答连续视频展示故障、不索取身份证/密码 |
| K03 | Pass | 到账 FAQ 在来源中；回答银行卡 3–7 工作日并限定为参考时效 |
| K04 | Pass | 订单物流 FAQ 在来源中；先核对签收人与凭证，不能仅凭描述直接退款 |
| K05 | Pass | 电源故障文档在来源中；鼓包发热时停止充电、隔离易燃物、联系人工/专业人员 |
| K06 | Pass | 会员售后权益在来源中；不豁免凭证审核和安全验证 |
| K07 | Pass | 退款 SOP 在来源中；依次覆盖意图、订单、展示申请内容、确认 |
| K08 | Pass | 支付安全提醒在来源中；拒绝索取密码、验证码、CVV、远控权限 |
| C03 | Pass | 第二轮准确回答刚查的合成订单 `202610227103`，没有多余工具调用 |
| C06 | Pass | 无可核验订单号，图为 `needs_clarification`，回答要求订单号，未编造业务状态 |

R05 的“澄清”不等于完整退款业务成功；C05 的正确运单号也不等于正确工具选择。K01 的来源命中不等于答案完整。三者均按原严格口径留在非通过项。

### 受控写操作与持久化核对

最终 R01–R08 执行器先读 MySQL 订单退款工单数，再读 Pending Action、Graph 快照与确认接口，最后再次读 DB。本轮又用 `scripts/verify_p1_refund.py` 独立只读核对 8 单：R01/R03/R07 为 `rejected` 且 0 工单；R02/R04/R06/R08 为 `executed` 且各 1 条 `open` 退款申请工单；R05 无确认单且 0 工单。每个批准单的工单有与确认单相联的 `refund:<confirmation_id>` 幂等键；R04 重复批准后仍为 1 条。7 个产生 Pending 的场景在批准/拒绝前均是 0 工单，Graph `next_nodes/task_names` 为 `await_confirmation`。这些证据只证明本地模拟业务的一次退款申请写入及固定重放窗口，不能推断全故障窗口全局恰好一次或真实支付退款。

计划来源逐例从最终 Graph 快照读取：R01/R03/R04/R07/R08 为 `llm_generated`，R02/R06 为 `llm_repaired`，R05 尚未生成计划。此轮退款通过项没有把 `rule_fallback` 记为模型自主规划；模型修复调用也没有被并入一次生成。`llm_repaired` 不代表模型理解了全部业务约束，仍需检查计划参数和订单归属。

### 代码、测试与知识边界

- `src/customer_service_app/services/question_router.py`：明确退款申请、政策咨询及原句/改写句的意图保留；解决 R03/R07/R08、K02/K03/K07、R06 的路由边界。对应 `tests/test_question_router.py`；先失败后通过，并有“如何申请退款”“不要提交退款申请”等相邻负例。
- `src/customer_service_app/services/question_rewrite_service.py`：仅在可信上下文订单号已存在、`missing_fields=[]`、明确只读订单/物流问题时清除多余澄清，不为缺订单或退款写入清除。对应 `tests/test_question_rewrite_service.py`。
- `src/customer_service_app/domain/planning.py`、`services/planner_service.py`、`workflows/nodes.py`：计划添加 `origin` 并写入 Trace，区分原生生成、模型修复、规则回退；对应 `tests/test_planner_service.py`、`tests/test_p1_fault_boundaries.py`。
- `scripts/evaluate_p2_security.py`、`scripts/evaluate_p2_faults.py`：加独立输出路径参数，避免覆盖 P2 原始报告；对应 `tests/test_p2_runner_output_paths.py`。
- 无 Embedding 模型、Qdrant 检索算法、知识文档或评测判据变更；修复是 Agent 路由/改写/可观测性，不可写成“混合检索优化”。

完整测试：`153 passed, 3 skipped, 1 warning`（passlib 引用 Python `crypt` 的废弃警告）；`ruff check --select E4,E7,E9,F` 针对修改文件通过，`git diff --check` 无空白错误。全规则 Ruff 存在原文件的格式/升级建议和容器测试目录未挂载造成的 `E902`，不把那次非目标命令写成通过。隔离 JWT harness 退出时有 `aiomysql` 的 event-loop-closed 析构警告，4 例评分仍通过；需在后续清理测试生命周期。

独立 Dense 检索复测在 `reports/p2_1_rag_2026-10-22.json`/`.md`：有效知识题 18，Hit@1 0.5556、Hit@3/5 0.6667、MRR 0.6111；有效期外、实时问题另列不混入分母。与旧含过期来源的 Hit@5 0.65/MRR 0.60 题集不同，不可称为检索收益；Faithfulness 未被自动证明。配置虽名 `hybrid`，OpenSearch 关闭，实测 Dense。

## 阶段判断与下一步门槛

P2.1 的“定位—最小修复—40 例复测—人工复核—交叉 DB 验证”已完成，但不是生产上线或 P3 已验收。进入下一阶段前优先处理三件事：

1. **退款参数治理**：当前明确请求即使缺充分原因，模型有时会给出泛化退款原因及 `refund_type` 并产生 Pending；R05 却因缺原因安全澄清。应明确最低必填字段和订单状态/退货方式规则，在后端确认前统一校验，不能靠模型随机决定。
2. **回复与工具一致性**：C05 运单号虽正确但调用订单工具；K01 政策时限未完整作答。对只读工具选择及知识回答完整性建立独立任务级与工具级指标，不为提高通过率硬改固定判据。
3. **可复现安全/评测证据**：常驻配置未启用鉴权；需真正开启身份边界部署验证。评测需多次同集运行或置信区间、控制中转波动，且解决 JWT TestClient 数据库连接关闭警告；当前 40 例只有一次最终抽样，不能报告稳定成功率或 SLA。

本阶段不启动 MCP、OpenSearch、多 Agent、P3；不推送代码。原用户改动 `docker-compose.yml`、`.dockerignore`、`.serena/` 保持原状。
