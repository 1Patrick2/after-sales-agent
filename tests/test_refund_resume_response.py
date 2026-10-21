from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from customer_service_app.core.exceptions import AppError
from customer_service_app.domain.planning import AgentPlan, PlanStep
from customer_service_app.services.customer_service_agent import CustomerServiceAgent
from customer_service_app.workflows.nodes import CustomerServiceGraphNodes


@pytest.mark.asyncio
async def test_completed_confirmation_cannot_resume_graph_again() -> None:
    agent = CustomerServiceAgent.__new__(CustomerServiceAgent)
    agent._session = AsyncMock()
    agent._confirmation_service = SimpleNamespace(
        get_owned=AsyncMock(return_value=SimpleNamespace(
            status="executed", langgraph_thread_id="thread-1"
        ))
    )
    agent._graph_runtime = SimpleNamespace(resume=AsyncMock())
    agent._graph_context = object()
    agent._graph_nodes = SimpleNamespace(to_response=lambda state: state)

    with pytest.raises(AppError) as exc:
        await agent._resume_confirmation_unlocked(
            tenant_id="default", user_id="p0_acceptance",
            confirmation_id="confirmation-1", decision="approve", reason=None,
        )

    assert exc.value.status_code == 409
    agent._graph_runtime.resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_approved_plan_clears_confirmation_prompt_and_exposes_write_result() -> None:
    nodes = CustomerServiceGraphNodes.__new__(CustomerServiceGraphNodes)
    nodes._confirmation_service = SimpleNamespace(
        get_owned=AsyncMock(return_value=SimpleNamespace(
            created_at=datetime.now(timezone.utc), tool_name="create_refund_case"
        )),
        approve=AsyncMock(return_value={"ticket_id": "ticket-1", "status": "open"}),
    )
    nodes._trace_service = SimpleNamespace(mark_running=AsyncMock(), step=AsyncMock())
    nodes._require_run = AsyncMock(return_value=object())
    plan = AgentPlan(
        plan_id="plan-1", conversation_id="conversation-1", user_goal="申请退款",
        steps=[PlanStep(
            step_id="step-1", title="申请退款", goal="创建退款申请工单",
            action_type="confirm", tool_name="create_refund_case",
        )],
    )
    state = {
        "tenant_id": "default", "user_id": "p0_acceptance", "run_id": "run-1",
        "pending_confirmation": {"id": "confirmation-1"},
        "confirmation_decision": {"confirmation_id": "confirmation-1", "decision": "approve"},
        "flow_origin": "plan", "plan": plan.model_dump(mode="json"),
        "active_step_id": "step-1", "final_answer": "请确认是否继续提交。",
    }

    result = await nodes.apply_confirmation(state)

    assert result.goto == "execute_plan_step"
    assert result.update["final_answer"] is None
    assert result.update["tool_results"][0]["payload"]["result"]["ticket_id"] == "ticket-1"
