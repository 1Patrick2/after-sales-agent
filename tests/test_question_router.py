from __future__ import annotations

import pytest

from customer_service_app.domain.schemas import ChatRequest
from customer_service_app.services.question_router import QuestionRouter


def test_policy_question_is_scoped_to_policy_documents() -> None:
    decision = QuestionRouter().route("七天无理由退货的条件和处理流程是什么？")

    assert decision.source == "knowledge"
    assert decision.execution_mode == "direct_answer"
    assert {"policy", "matrix", "faq", "sop"}.issubset(decision.document_types)


def test_realtime_lookup_skips_rag_and_uses_tool() -> None:
    decision = QuestionRouter().route("帮我查询订单 202607180001 现在的物流状态")

    assert decision.source == "realtime_tool"
    assert decision.execution_mode == "direct_tool"
    assert decision.document_types == []


def test_order_policy_question_uses_hybrid_route() -> None:
    decision = QuestionRouter().route(
        "订单 202607180001 是否可以退货？",
        planner_enabled=True,
    )

    assert decision.source == "hybrid"
    assert decision.execution_mode == "rag_then_tool"
    assert "policy" in decision.document_types


def test_policy_word_does_not_turn_stable_question_into_realtime_tool() -> None:
    decision = QuestionRouter().route("退款怎么处理？")

    assert decision.source == "knowledge"
    assert decision.execution_mode == "direct_answer"


def test_complex_request_enters_planner_when_enabled() -> None:
    request = ChatRequest(
        user_id="u1",
        question="先查询订单 202607180001，如果符合条件就申请退款，否则转人工",
    )

    decision = QuestionRouter().route(request.question, planner_enabled=True)

    assert decision.execution_mode == "planner"
    assert decision.reason == "complex_dependency_requires_planner"


def test_explicit_refund_submission_enters_planner_for_confirmation() -> None:
    router = QuestionRouter()

    submission = router.route(
        "请为订单 202610210001 提交退款申请，原因是耳机持续杂音",
        planner_enabled=True,
    )
    policy_question = router.route("如何申请退款？", planner_enabled=True)

    assert submission.execution_mode == "planner"
    assert policy_question.execution_mode != "planner"


@pytest.mark.parametrize(
    "question",
    [
        "我确认要给订单202610219203发起退款申请。",
        "订单202610219207需要退款申请，请提交。",
        "请提交订单202610219208的退款申请，不要直接执行支付退款。",
    ],
)
def test_explicit_refund_application_variants_enter_confirmation_planner(
    question: str,
) -> None:
    decision = QuestionRouter().route(question, planner_enabled=True)

    assert decision.execution_mode == "planner"


@pytest.mark.parametrize(
    "question",
    [
        "退款申请处理后一般多久能到账？",
        "客服创建退款申请前应该做哪些步骤？",
        "如何提交退款申请？",
        "请问如何提交退款申请？",
        "不要提交退款申请，我只想了解政策。",
    ],
)
def test_refund_consultation_does_not_enter_write_planner(question: str) -> None:
    decision = QuestionRouter().route(question, planner_enabled=True)

    assert decision.execution_mode != "planner"
    assert decision.source == "knowledge"


def test_quality_evidence_question_keeps_policy_documents_in_scope() -> None:
    decision = QuestionRouter().route(
        "耳机功能异常申请售后需要哪些凭证？", planner_enabled=True
    )

    assert decision.source == "knowledge"
    assert "policy" in decision.document_types


def test_rewrite_does_not_discard_original_policy_scope() -> None:
    decision = QuestionRouter().route(
        "耳机功能异常申请售后需要哪些凭证？",
        resolved_question="耳机功能异常申请售后需要提供哪些凭证或证明材料？",
        planner_enabled=True,
    )

    assert decision.source == "knowledge"
    assert "policy" in decision.document_types


def test_rewrite_cannot_turn_refund_submission_into_consultation() -> None:
    router = QuestionRouter()
    original = "请为这个订单提交退款申请。"
    rewritten = "订单202610228206当前已发货，如何提交退款申请？该状态下规则是什么？"
    request = ChatRequest(user_id="u1", question=original)

    decision = router.route(original, resolved_question=rewritten, planner_enabled=True)

    assert decision.execution_mode == "planner"
    assert router.should_plan(request, resolved_question=rewritten) is True
