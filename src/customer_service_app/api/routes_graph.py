from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from customer_service_app.api.dependencies import (
    get_customer_service_agent,
    require_roles,
)
from customer_service_app.core.exceptions import AppError
from customer_service_app.core.security import CurrentPrincipal, authorize_identity
from customer_service_app.domain.schemas import GraphStateView
from customer_service_app.infrastructure.db.repositories import AgentRunRepository
from customer_service_app.infrastructure.db.session import get_db_session
from customer_service_app.services.customer_service_agent import CustomerServiceAgent


router = APIRouter(prefix="/graph", tags=["graph"])
"""Graph 调试接口路由组。

最终路径是 `/api/v1/graph/...`，主要给运营验证台和开发排查使用。
"""


@router.get("/threads/{thread_id}", response_model=GraphStateView)
async def get_graph_thread(
    thread_id: str,
    agent: CustomerServiceAgent = Depends(get_customer_service_agent),
    session: AsyncSession = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(require_roles("operator", "admin")),
) -> GraphStateView:
    """Inspect a sanitized LangGraph checkpoint for operations and debugging."""

    state = await agent.graph_state(thread_id=thread_id)
    run_id = str(state.values.get("run_id") or "")
    run = await AgentRunRepository(session).get_run(run_id=run_id) if run_id else None
    if run is None:
        raise AppError("Graph thread not found", code="graph_thread_not_found", status_code=404)
    authorize_identity(principal, tenant_id=run.tenant_id, user_id=run.user_id)
    return state
