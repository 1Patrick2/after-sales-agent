from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from customer_service_app.core.exceptions import AppError
from customer_service_app.services.tool_registry import ToolExecutionContext, ToolRegistry
from customer_service_app.tools.after_sales_tools import REFUND_CASE_TOOL


def _context(gateway) -> ToolExecutionContext:
    return ToolExecutionContext(
        tenant_id="tenant-a", user_id="customer-a", conversation_id="conversation-a",
        session=object(), search_client=object(), business_gateway=gateway,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_refund_tool_rejects_model_supplied_identity_fields() -> None:
    gateway = SimpleNamespace(create_refund_case=AsyncMock())
    registry = ToolRegistry()
    registry.register(REFUND_CASE_TOOL)

    with pytest.raises(AppError) as error:
        await registry.execute_dict(
            name="create_refund_case",
            arguments={
                "order_id": "209912310001", "reason": "尺寸不合适",
                "refund_type": "return_refund", "user_id": "customer-b",
                "tenant_id": "tenant-b",
            },
            context=_context(gateway),
        )

    assert error.value.status_code == 400
    assert error.value.code == "tool_arguments_invalid"
    gateway.create_refund_case.assert_not_awaited()


@pytest.mark.asyncio
async def test_refund_tool_uses_trusted_context_for_valid_arguments() -> None:
    gateway = SimpleNamespace(
        create_refund_case=AsyncMock(return_value={"ticket_id": "ticket-a", "status": "open"})
    )
    registry = ToolRegistry()
    registry.register(REFUND_CASE_TOOL)

    result = await registry.execute_dict(
        name="create_refund_case",
        arguments={
            "order_id": "209912310001", "reason": "尺寸不合适",
            "refund_type": "return_refund",
        },
        context=_context(gateway),
    )

    assert result["ticket_id"] == "ticket-a"
    assert gateway.create_refund_case.await_args.kwargs["tenant_id"] == "tenant-a"
    assert gateway.create_refund_case.await_args.kwargs["user_id"] == "customer-a"
