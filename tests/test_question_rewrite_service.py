from __future__ import annotations

import json

from customer_service_app.core.config import Settings
from customer_service_app.domain.memory import ShortTermContext
from customer_service_app.domain.schemas import ChatMessage
from customer_service_app.infrastructure.llm.base import LLMResponse, LLMToolCall
from customer_service_app.services.question_rewrite_service import QuestionRewriteService


class RewriteLLM:
    def __init__(
        self,
        *,
        standalone_question: str,
        needs_clarification: bool = False,
        missing_fields: list[str] | None = None,
    ):
        self._standalone_question = standalone_question
        self._needs_clarification = needs_clarification
        self._missing_fields = missing_fields or []

    async def chat(self, messages, **kwargs):
        payload = {
            "standalone_question": self._standalone_question,
            "dense_query": self._standalone_question,
            "sparse_query": "202607180001 退货 签收 政策",
            "intent": "return_policy",
            "entities": {"order_id": "202607180001"},
            "missing_fields": self._missing_fields,
            "needs_rewrite": True,
            "needs_clarification": self._needs_clarification,
            "clarification_question": "请确认订单号？" if self._needs_clarification else None,
            "confidence": 0.92,
            "reason": "resolved_from_recent_message",
        }
        return LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(
                    id="rewrite-1",
                    name="submit_query_rewrite",
                    arguments=json.dumps(payload, ensure_ascii=False),
                )
            ],
            model="rewrite-model",
        )


async def test_vague_question_without_context_requests_clarification() -> None:
    service = QuestionRewriteService(
        settings=Settings(),
        llm_client=RewriteLLM(standalone_question="unused"),
    )

    result, response = await service.resolve(
        question="那个还能退吗？",
        context=ShortTermContext(),
        model="rewrite-model",
    )

    assert response is None
    assert result.missing_fields == ["business_reference"]
    assert result.needs_rewrite is True
    assert result.needs_clarification is True
    assert result.clarification_question


async def test_rewrite_uses_trusted_context_and_preserves_business_id() -> None:
    standalone = "订单 202607180001 已签收，是否符合退货政策？"
    service = QuestionRewriteService(
        settings=Settings(),
        llm_client=RewriteLLM(standalone_question=standalone),
    )
    context = ShortTermContext(
        recent_messages=[
            ChatMessage(role="user", content="我的订单是 202607180001"),
            ChatMessage(role="assistant", content="订单显示已签收"),
        ]
    )

    result, response = await service.resolve(
        question="那个还能退吗？",
        context=context,
        model="rewrite-model",
    )

    assert response is not None
    assert result.source == "llm"
    assert result.needs_rewrite is True
    assert result.standalone_question == standalone


async def test_rewrite_rejects_invented_business_id() -> None:
    service = QuestionRewriteService(
        settings=Settings(),
        llm_client=RewriteLLM(
            standalone_question="订单 999999999999 是否可以退货？"
        ),
    )
    context = ShortTermContext(
        recent_messages=[ChatMessage(role="user", content="订单 202607180001")]
    )

    result, _ = await service.resolve(
        question="那个还能退吗？",
        context=context,
        model="rewrite-model",
    )

    assert result.source == "fallback"
    assert "999999999999" not in result.standalone_question


async def test_read_only_followup_with_trusted_order_does_not_repeat_clarification() -> None:
    service = QuestionRewriteService(
        settings=Settings(),
        llm_client=RewriteLLM(
            standalone_question="查询订单 202607180001 的物流进度",
            needs_clarification=True,
        ),
    )
    context = ShortTermContext(
        recent_messages=[
            ChatMessage(role="user", content="请看订单 202607180001"),
            ChatMessage(role="assistant", content="请确认查询内容"),
        ]
    )

    result, response = await service.resolve(
        question="它的物流进度呢？",
        context=context,
        model="rewrite-model",
    )

    assert response is not None
    assert result.standalone_question == "查询订单 202607180001 的物流进度"
    assert result.needs_clarification is False


async def test_followup_with_missing_order_still_requests_clarification() -> None:
    service = QuestionRewriteService(
        settings=Settings(),
        llm_client=RewriteLLM(
            standalone_question="查询订单 202607180001 的物流进度",
            needs_clarification=True,
            missing_fields=["订单号"],
        ),
    )
    context = ShortTermContext(
        recent_messages=[ChatMessage(role="user", content="请看订单 202607180001")]
    )

    result, _ = await service.resolve(
        question="它的物流进度呢？", context=context, model="rewrite-model"
    )

    assert result.needs_clarification is True
