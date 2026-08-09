# Enterprise Customer Service Agent V2

一个面向消费者和企业客户服务场景的 AI Agent 后端项目。当前重点是会话、有界任务规划、混合知识检索、工具调用、LangGraph 人工确认与恢复、MCP 业务边界、成本策略和结果落库。

相比 V1 版本，V2 围绕 LangGraph 编排、HIL（checkpoint / interrupt / resume）、MCP 业务服务边界、短期与长期记忆、模型成本治理，以及观测与评估能力持续演进。

## 项目定位

项目将大模型用于问题理解、有限规划和工具选择；业务事实查询、权限校验、风险控制和数据写入由后端服务负责。高风险动作需要 HIL 确认、幂等控制和审计关联。

## 当前能力

- LangGraph Checkpoint、`interrupt` 与恢复，确认单与 Graph thread 绑定。
- 复杂请求触发有界 Planner/ReAct，简单问题跳过规划模型。
- Qdrant/Milvus 向量召回与 OpenSearch BM25 并行召回，通过 RRF 融合，并支持可选 HTTP Reranker。
- Markdown 标题、段落、句子边界和重叠窗口切块，向量索引与 BM25 索引共用 chunk ID。
- 知识文档按内容哈希、版本和生效时间增量同步，下线时联动清理双索引与相关语义缓存。
- 长期记忆支持来源校验、过期时间、用户查询/纠正/删除，以及用户级记忆开关。
- Tool Registry、Business Gateway 和独立 after-sales MCP 服务，读写工具分级治理。
- MCP HTTP 服务支持服务 JWT、调用上下文签名和租户/用户二次校验；写操作额外校验 Approval Token。
- PostgreSQL Checkpoint 用于跨进程恢复 LangGraph 的中断任务，MCP 工具契约支持 TTL 缓存。
- 人工队列、模拟坐席接管、处理结论和 Bot 恢复闭环。
- 租户级模型、历史窗口、RAG 数量、Rerank 和缓存策略调整。
- Prometheus 运行指标、OpenTelemetry 分布式追踪，以及可选的 Grafana/Tempo 观测栈。

## 成本治理

V2 的成本治理目标不是简单拒绝服务，而是在租户日用量接近或超过预算时，动态调整运行策略，尽量保持客服链路可用：

- 降级模型时同步降低任务复杂度，减少复杂规划、多工具链和长推理，优先使用确定性规则完成可控判断。
- 低成本模型使用更明确的结构化提示词，降低模型自由发挥空间，提高意图识别和工具参数生成的稳定性。
- 工具调用继续使用严格参数校验，缺少订单号、原因、确认 token 等关键字段时先追问或中断，不直接执行业务动作。
- 对包含“这个、那个、刚才、上面”等模糊指代的问题，优先做问题改写或补充短期记忆，避免低成本模型误解上下文。
- 高风险动作不随模型降级而降低安全标准，退款、补偿、换货、转人工等操作仍然需要人工确认、幂等控制和审计记录。
- 成本策略同时调整模型、RAG 召回数量、历史窗口、rerank 和缓存优先级，而不是只替换一个更便宜的模型名称。

## 技术栈

- Python 3.11+
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x Async ORM
- MySQL
- Redis
- Qdrant / Milvus
- OpenSearch BM25
- HTTP Reranker adapter
- LangGraph
- MCP Python SDK
- OpenAI-compatible Chat Completions API
- OpenAI-compatible Embeddings API
- pytest
- ruff

## 项目结构

```text
enterprise-customer-service-agent-v2/
  Dockerfile
  docker-compose.yml
  pyproject.toml
  requirements.txt
  assets/
  knowledge_base/
  scripts/
    check_env.py
    init_db.py
    seed_sample_data.py
    ingest_docs.py
    run_dev.py
    run_after_sales_mcp_server.py
  mcp_services/
    after_sales_server/
  src/customer_service_app/
    api/
    core/
    domain/
    infrastructure/
      cache/
      db/
      embeddings/
      knowledge_ingestion/
      lexical_search/
      llm/
      mcp/
      rerank/
      search/
      vector_store/
    prompts/
    services/
    tools/
    workflows/
    web/
  tests/
```

## 配置

复制环境变量模板：

```bash
cp .env.example .env
```

主要配置：

```dotenv
RUNTIME_ENV=production
ALLOWED_ORIGINS=https://console.example.com

LLM_PROVIDER=openai_compatible
LLM_API_KEY=<your-llm-api-key>
LLM_BASE_URL=https://llm-provider.example.com/v1
LLM_MODEL=<chat-model-name>

EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_API_KEY=<your-embedding-api-key>
EMBEDDING_BASE_URL=https://embedding-provider.example.com/v1
EMBEDDING_MODEL=<embedding-model-name>
EMBEDDING_DIMENSION=1024

DATABASE_URL=mysql+aiomysql://<user>:<password>@<mysql-host>:3306/<database>?charset=utf8mb4
REDIS_URL=redis://:<password>@<redis-host>:6379/0
REQUEST_LOCK_ENABLED=true
REQUEST_LOCK_TTL_SECONDS=120

VECTOR_STORE_PROVIDER=qdrant
QDRANT_URL=https://qdrant.example.com
QDRANT_API_KEY=<your-qdrant-api-key>
QDRANT_COLLECTION=customer_service_knowledge

MILVUS_URI=https://milvus.example.com
MILVUS_TOKEN=<your-milvus-token>
MILVUS_COLLECTION=customer_service_knowledge

RETRIEVAL_MODE=hybrid
OPENSEARCH_ENABLED=true
OPENSEARCH_URL=https://<opensearch-host>:9200
OPENSEARCH_INDEX=customer_service_knowledge

RERANK_ENABLED=false
RERANK_BASE_URL=https://<rerank-provider>/v1/rerank
RERANK_MODEL=<rerank-model-name>

MCP_AFTER_SALES_ENABLED=true
MCP_AFTER_SALES_URL=https://mcp-after-sales.example.com/mcp
MCP_APPROVAL_SIGNING_SECRET=<random-signing-secret>

SECURITY_ENABLED=true
JWT_SECRET_KEY=<random-jwt-secret>
JWT_ISSUER=<identity-provider>
JWT_AUDIENCE=<service-audience>

METRICS_ENABLED=true
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=https://<otel-collector-host>:4318
```

客户端重试同一轮请求时，应携带同一个 `Idempotency-Key` 请求头。服务会按租户和用户隔离该键，并复用已经落库的响应：

```bash
curl -X POST "https://<agent-host>/api/v1/chat" \
  -H "Authorization: Bearer <access-token>" \
  -H "Idempotency-Key: <client-generated-request-key>" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"ignored-by-server","user_id":"ignored-by-server","question":"我的订单到哪里了？"}'
```

## 部署说明

主服务可以作为 FastAPI 应用部署，并依赖以下独立基础设施和业务服务：

- MySQL：保存会话、消息、订单、售后工单、确认记录、审计日志和长期记忆。
- Redis：承接语义缓存、运行锁、限流策略和轻量计数。
- Qdrant / Milvus：承接客户服务知识的向量检索。
- OpenSearch：承接规则编号、产品名和专有词等 BM25 关键词检索。
- Reranker（可选）：对融合后的少量候选块做二次排序。
- after-sales MCP service：提供订单、物流、退款、补偿、换货、转人工等业务能力。
- LangSmith / Prometheus / Grafana：提供链路追踪、指标、看板和运行分析。

典型启动顺序：

```bash
python scripts/check_env.py
# 生产环境使用 Alembic 管理数据库版本
alembic upgrade head
python scripts/seed_sample_data.py
python scripts/ingest_docs.py knowledge_base --tenant-id <tenant-id>
python scripts/run_after_sales_mcp_server.py
uvicorn customer_service_app.main:app --host 0.0.0.0 --port <port>
```

`python scripts/init_db.py` 只适合本地全新数据库的快速初始化，不替代生产迁移。

知识目录需要作为租户完整数据源进行对账时，显式开启缺失文档清理：

```bash
python scripts/ingest_docs.py knowledge_base \
  --tenant-id <tenant-id> \
  --prune-missing
```

该模式会把目录中已删除的文档同步下线，并清理对应向量、BM25 索引和语义缓存引用。

完成入库后，可用真实检索链路计算 Hit@K 和 MRR：

```bash
python scripts/evaluate_retrieval.py --tenant-id <tenant-id> --top-k 5
python scripts/evaluate_retrieval.py --tenant-id <tenant-id> --top-k 5 --rerank
```

容器化部署时，通过目标平台注入环境变量，并使用项目中的 Dockerfile 或 Compose 模板启动服务。

Compose 中的 OpenSearch、PostgreSQL Checkpointer 和观测组件使用可选 profile，
可以按部署需要组合启动：

```bash
docker compose --profile search --profile durable --profile observability up -d
```

Prometheus 从 `/metrics` 拉取 HTTP、Graph、LLM、工具、MCP、缓存、Planner 和检索指标；
OpenTelemetry 将 FastAPI 与 HTTP 客户端 trace 发送到 OTLP Collector，再由 Tempo 保存并在
Grafana 中查询。生产环境应在网关层限制 `/metrics` 和 Grafana 的访问范围。

## MCP 服务

after-sales MCP 服务将售后能力暴露为独立治理的业务工具：

- `query_order_status`
- `query_logistics_status`
- `query_price_protection`
- `query_customer_profile`
- `create_refund_case`
- `create_compensation_case`
- `create_exchange_case`
- `transfer_to_human`

只读工具需要经过服务身份、调用上下文签名和租户/用户归属校验。写入工具还需要签名确认 token、唯一 `jti` 和幂等键，避免同一个已确认动作被重复执行。

## API 示例

```bash
curl -X POST "https://api.example.com/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant_001",
    "user_id": "user_001",
    "conversation_id": null,
    "question": "我的订单 202606040001 已经签收了，但是商品有破损，我想申请退款或者补偿。",
    "history": [],
    "metadata": {}
  }'
```

## 测试

```bash
pytest -q
ruff check src tests scripts mcp_services/after_sales_server/src
```

## License

MIT
