from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from customer_service_app.domain.schemas import ChatRequest
from customer_service_app.services.customer_service_agent import CustomerServiceAgent


@pytest.mark.asyncio
async def test_resume_checkpoint_can_finish_before_mysql_commit_fails() -> None:
    """A PG-complete/MySQL-rolled-back split must be reported, not called exactly-once."""
    agent = CustomerServiceAgent.__new__(CustomerServiceAgent)
    agent._session = AsyncMock()
    agent._session.commit.side_effect = RuntimeError("synthetic MySQL commit failure")
    agent._confirmation_service = SimpleNamespace(
        get_owned=AsyncMock(return_value=SimpleNamespace(
            status="pending", langgraph_thread_id="thread-a",
        ))
    )
    agent._graph_runtime = SimpleNamespace(resume=AsyncMock(return_value={"status": "completed"}))
    agent._graph_context = object()
    agent._graph_nodes = SimpleNamespace(to_response=lambda state: state)

    with pytest.raises(RuntimeError, match="synthetic MySQL commit failure"):
        await agent._resume_confirmation_unlocked(
            tenant_id="tenant-a", user_id="user-a", confirmation_id="confirmation-a",
            decision="approve", reason=None,
        )

    agent._graph_runtime.resume.assert_awaited_once()
    agent._session.commit.assert_awaited_once()
    agent._session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_mysql_pending_action_can_commit_before_checkpoint_fails() -> None:
    """A pre-interrupt MySQL commit cannot be undone by the facade rollback."""
    agent = CustomerServiceAgent.__new__(CustomerServiceAgent)
    agent._session = AsyncMock()
    agent._human_support_service = object()
    agent._graph_context = object()

    async def fail_after_mysql_commit(**kwargs: object) -> dict:
        await agent._session.commit()  # mirrors create_pending_action before interrupt
        raise RuntimeError("synthetic PostgreSQL checkpoint failure")

    agent._graph_runtime = SimpleNamespace(invoke=AsyncMock(side_effect=fail_after_mysql_commit))
    request = ChatRequest(tenant_id="tenant-a", user_id="user-a", question="退款")

    with pytest.raises(RuntimeError, match="synthetic PostgreSQL checkpoint failure"):
        await agent._answer_unlocked(request)

    agent._session.commit.assert_awaited_once()
    agent._session.rollback.assert_awaited_once()
