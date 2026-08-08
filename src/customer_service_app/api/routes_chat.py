from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse

from customer_service_app.api.dependencies import get_customer_service_agent, require_roles
from customer_service_app.core.security import CurrentPrincipal, authorize_identity
from customer_service_app.domain.schemas import ChatRequest, ChatResponse
from customer_service_app.services.customer_service_agent import CustomerServiceAgent


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        max_length=128,
    ),
    agent: CustomerServiceAgent = Depends(get_customer_service_agent),
    principal: CurrentPrincipal = Depends(
        require_roles("customer", "agent", "operator", "admin")
    ),
) -> ChatResponse:
    """返回完整回答和执行轨迹。"""
    tenant_id, user_id = authorize_identity(
        principal,
        tenant_id=request.tenant_id,
        user_id=request.user_id,
    )
    secured_request = _secure_request(
        request,
        tenant_id=tenant_id,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )
    return await agent.answer(secured_request)


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        max_length=128,
    ),
    agent: CustomerServiceAgent = Depends(get_customer_service_agent),
    principal: CurrentPrincipal = Depends(
        require_roles("customer", "agent", "operator", "admin")
    ),
) -> StreamingResponse:
    """流式聊天接口，返回 text/event-stream。"""
    tenant_id, user_id = authorize_identity(
        principal,
        tenant_id=request.tenant_id,
        user_id=request.user_id,
    )
    secured_request = _secure_request(
        request,
        tenant_id=tenant_id,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )
    return StreamingResponse(
        agent.stream_answer(secured_request),
        media_type="text/event-stream",
    )


def _secure_request(
    request: ChatRequest,
    *,
    tenant_id: str,
    user_id: str,
    idempotency_key: str | None,
) -> ChatRequest:
    """统一写入可信身份和客户端幂等键，避免两个入口处理不一致。"""
    metadata = dict(request.metadata)
    if idempotency_key:
        metadata["idempotency_key"] = idempotency_key.strip()
    return request.model_copy(
        update={"tenant_id": tenant_id, "user_id": user_id, "metadata": metadata}
    )
