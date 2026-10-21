import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from customer_service_app.core.config import Settings
from customer_service_app.core.exceptions import AppError, ExternalServiceError
from customer_service_app.domain.schemas import ChatRequest
from customer_service_app.infrastructure.llm.openai_compatible import OpenAICompatibleLLMClient
from customer_service_app.services.planner_service import PlannerService
from customer_service_app.services.tool_registry import ToolExecutionContext, ToolRegistry, ToolSpec
from customer_service_app.tools.default_registry import build_default_tool_registry


@pytest.mark.asyncio
async def test_model_error_does_not_expose_provider_authorization(caplog: pytest.LogCaptureFixture) -> None:
    secret = "synthetic-test-secret-not-a-real-key"
    client = OpenAICompatibleLLMClient(Settings())
    create = AsyncMock(side_effect=RuntimeError(f"Authorization: Bearer {secret}"))
    with patch.object(
        OpenAICompatibleLLMClient, "client", new_callable=PropertyMock
    ) as client_property:
        client_property.return_value = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        with caplog.at_level(logging.INFO):
            with pytest.raises(ExternalServiceError) as error:
                await client.chat([{"role": "user", "content": "test"}])
    assert secret not in str(error.value)
    assert secret not in caplog.text
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_model_error_does_not_expose_provider_authorization(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "synthetic-stream-secret-not-a-real-key"
    client = OpenAICompatibleLLMClient(Settings())
    create = AsyncMock(side_effect=RuntimeError(f"Authorization: Bearer {secret}"))
    with patch.object(
        OpenAICompatibleLLMClient, "client", new_callable=PropertyMock
    ) as client_property:
        client_property.return_value = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        with caplog.at_level(logging.WARNING):
            with pytest.raises(ExternalServiceError) as error:
                async for _ in client.stream_chat([{"role": "user", "content": "test"}]):
                    pass
    assert secret not in str(error.value)
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_tool_timeout_cancels_cooperative_handler_before_side_effect() -> None:
    writes = []

    async def slow_handler(arguments: dict, context: ToolExecutionContext) -> dict:
        await asyncio.sleep(0.05)
        writes.append(arguments["order_id"])
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="slow_read", description="test", parameters={
            "type": "object", "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"], "additionalProperties": False,
        }, handler=slow_handler, timeout_seconds=0.01,
    ))
    context = ToolExecutionContext(
        tenant_id="tenant-a", user_id="user-a", conversation_id=None,
        session=object(), search_client=object(),  # type: ignore[arg-type]
    )
    with pytest.raises(TimeoutError):
        await registry.execute_dict(
            name="slow_read", arguments={"order_id": "test-order"}, context=context,
        )
    await asyncio.sleep(0.06)
    assert writes == []


@pytest.mark.asyncio
async def test_tool_schema_rejects_model_supplied_identity_before_handler() -> None:
    handler = AsyncMock(return_value={"ok": True})
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="read", description="test", parameters={
            "type": "object", "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"], "additionalProperties": False,
        }, handler=handler,
    ))
    context = ToolExecutionContext(
        tenant_id="tenant-a", user_id="user-a", conversation_id=None,
        session=object(), search_client=object(),  # type: ignore[arg-type]
    )
    with pytest.raises(AppError) as error:
        await registry.execute_dict(
            name="read", arguments={"order_id": "x", "tenant_id": "tenant-b"},
            context=context,
        )
    assert error.value.code == "tool_arguments_invalid"
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_planner_model_failure_uses_bounded_rule_fallback_without_executing_tool() -> None:
    model = SimpleNamespace(chat=AsyncMock(side_effect=ExternalServiceError("model unavailable")))
    service = PlannerService(tool_registry=build_default_tool_registry())
    plan, response = await service.build_plan(
        request=ChatRequest(
            tenant_id="tenant-a", user_id="user-a",
            question="查询订单 209912310001 并提交退款申请，原因是损坏",
        ),
        conversation_id="conversation-a", llm_client=model, model="test-model",
    )
    assert response is None
    assert plan is not None
    assert any(step.tool_name == "create_refund_case" and step.requires_confirmation for step in plan.steps)
    model.chat.assert_awaited_once()
