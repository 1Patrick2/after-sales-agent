from __future__ import annotations

import re
from collections.abc import Iterable

from customer_service_app.domain.query_rewrite import QueryRewriteResult
from customer_service_app.domain.routing import ExecutionMode, RouteDecision, RouteSource
from customer_service_app.domain.schemas import ChatRequest


class QuestionRouter:
    """使用确定性信号统一决定数据来源、知识范围和任务复杂度。"""

    _business_id_pattern = re.compile(
        r"(?<![A-Za-z0-9])(?:[A-Za-z]{2,8}-?)?\d{8,24}(?![A-Za-z0-9])"
    )
    _condition_words = ("如果", "然后", "同时", "再", "并且", "否则")
    _realtime_words = ("订单状态", "物流到哪", "快递到哪", "退款进度", "工单进度")
    _policy_words = ("规则", "政策", "条件", "期限", "是否可以", "怎么处理", "流程")
    _business_domains = (
        "订单",
        "物流",
        "快递",
        "运单",
        "退款",
        "退货",
        "换货",
        "工单",
        "投诉",
        "人工",
        "客服",
    )
    _query_words = ("查", "查询", "查看", "状态", "进度", "到哪", "现在", "当前")
    _action_words = (
        "申请",
        "创建",
        "取消",
        "修改",
        "提交",
        "转人工",
        "帮我查",
        "帮我申请",
        "帮我创建",
        "帮我取消",
        "帮我修改",
    )

    def route(
        self,
        question: str,
        *,
        resolved_question: str | None = None,
        rewrite: QueryRewriteResult | None = None,
        planner_enabled: bool = False,
    ) -> RouteDecision:
        """为当前问题生成一个可观测、可传递的路由决策。"""

        value = (resolved_question or question).strip()
        if not value:
            return RouteDecision(reason="empty_question")

        policy = self._is_policy(value, rewrite)
        realtime = self._is_realtime(value, policy=policy)
        source: RouteSource
        if realtime and policy:
            source = "hybrid"
        elif realtime:
            source = "realtime_tool"
        else:
            source = "knowledge"

        needs_plan = planner_enabled and self._should_plan_question(value)
        execution_mode: ExecutionMode
        if needs_plan:
            execution_mode = "planner"
        elif source == "realtime_tool":
            execution_mode = "direct_tool"
        elif source == "hybrid":
            execution_mode = "rag_then_tool"
        else:
            execution_mode = "direct_answer"

        document_types = self._document_types(value, source=source, policy=policy)
        return RouteDecision(
            source=source,
            execution_mode=execution_mode,
            document_types=document_types,
            confidence=self._confidence(value, source=source, policy=policy),
            reason=self._reason(source, policy=policy, needs_plan=needs_plan),
        )

    def should_plan(self, request: ChatRequest, *, resolved_question: str | None = None) -> bool:
        """零 Token 复杂度门禁，供 Planner 和主路由共同使用。"""

        question = (resolved_question or request.question).strip()
        return self._should_plan_question(question)

    def _should_plan_question(self, question: str) -> bool:
        """按纯文本判断复杂度，避免把改写后的长上下文重新校验成请求 DTO。"""

        if not question:
            return False
        if any(word in question for word in self._condition_words):
            return True

        intents = 0
        if self._contains_any(question, ("订单", "物流", "快递", "运单", "单号", "发货", "签收")):
            intents += 1
        if self._contains_any(question, ("退款", "退货", "退掉", "换货", "补发", "重新发")):
            intents += 1
        if self._contains_any(question, ("补偿", "赔偿", "价保", "保价", "差价", "优惠券")):
            intents += 1
        if self._contains_any(question, ("人工", "客服", "投诉", "举报", "升级处理", "12315")):
            intents += 1

        action_count = sum(
            question.count(word)
            for word in ("查询", "查看", "申请", "创建", "取消", "修改", "转", "处理")
        )
        order_ids = set(self._business_id_pattern.findall(question))
        # 两个业务名词并不等于两个执行步骤，例如“订单是否可以退货”
        # 仍是一次规则判断；只有出现动作、条件依赖或多实体时才启动 Planner。
        return (
            (intents >= 3 and action_count >= 1)
            or action_count >= 2
            or len(order_ids) >= 2
        )

    def _is_realtime(self, value: str, *, policy: bool) -> bool:
        if any(word in value for word in self._realtime_words):
            return True
        has_domain = any(word in value for word in self._business_domains)
        has_query_or_action = any(
            word in value for word in (*self._query_words, *self._action_words)
        )
        has_business_id = bool(self._business_id_pattern.search(value))
        # “退款怎么处理”“退货流程”是稳定政策问题；只有出现明确查询/操作
        # 动词或业务实体时，才把它升级为实时工具请求。
        if policy and not has_business_id:
            return False
        return has_domain and (has_query_or_action or has_business_id)

    def _is_policy(self, value: str, rewrite: QueryRewriteResult | None) -> bool:
        if rewrite is not None:
            intent = rewrite.intent.lower()
            if "policy" in intent or "faq" in intent:
                return True
        return any(word in value for word in self._policy_words)

    def _document_types(self, value: str, *, source: RouteSource, policy: bool) -> list[str]:
        if source == "realtime_tool" and not policy:
            return []

        scopes: set[str] = set()
        if policy:
            scopes.update({"policy", "matrix", "faq", "sop"})
        if self._contains_any(value, ("故障", "没电", "充不上", "安装", "保养", "使用", "无声")):
            scopes.update({"troubleshooting", "manual", "faq"})
        if self._contains_any(value, ("退款", "退货", "换货", "补偿", "赔偿")):
            scopes.update({"policy", "matrix", "sop", "risk", "faq"})
        if self._contains_any(value, ("物流", "快递", "发货", "时效")):
            scopes.update({"faq", "announcement", "sla"})
        if self._contains_any(value, ("权益", "会员", "价保", "保价", "差价", "优惠")):
            scopes.update({"benefit", "announcement", "policy", "matrix"})
        if self._contains_any(value, ("账户", "支付", "凭证", "风控", "异常")):
            scopes.update({"risk", "faq", "sop"})
        if self._contains_any(value, ("投诉", "升级", "人工", "客服")):
            scopes.update({"sop", "risk", "faq"})
        if self._contains_any(value, ("商家", "举证", "平台介入")):
            scopes.update({"merchant_rule", "policy", "sop"})
        return sorted(scopes)

    @staticmethod
    def _confidence(value: str, *, source: RouteSource, policy: bool) -> float:
        if source == "hybrid":
            return 0.82
        if source == "realtime_tool":
            return 0.9 if bool(re.search(r"\d{8,24}", value)) else 0.72
        return 0.78 if policy else 0.55

    @staticmethod
    def _reason(source: RouteSource, *, policy: bool, needs_plan: bool) -> str:
        if needs_plan:
            return "complex_dependency_requires_planner"
        if source == "hybrid":
            return "policy_evidence_and_realtime_fact_required"
        if source == "realtime_tool":
            return "realtime_business_fact_requires_tool"
        return "stable_policy_can_use_rag" if policy else "stable_knowledge_can_use_rag"

    @staticmethod
    def _contains_any(value: str, words: Iterable[str]) -> bool:
        return any(word in value for word in words)
