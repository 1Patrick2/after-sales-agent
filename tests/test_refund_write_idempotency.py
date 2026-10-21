from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from customer_service_app.core.exceptions import AppError
from customer_service_app.infrastructure.db.repositories import OrderRepository, TicketRepository
from customer_service_app.services.business_gateway import BusinessGateway
from customer_service_app.services.tool_registry import ToolExecutionContext
from customer_service_app.tools.after_sales_tools import create_refund_case


@pytest.mark.asyncio
async def test_confirmation_id_reaches_refund_ticket_unique_key() -> None:
    gateway = BusinessGateway(object())  # type: ignore[arg-type]
    context = ToolExecutionContext(
        tenant_id="tenant-a", user_id="user-a", conversation_id="conversation-a",
        session=object(), search_client=object(), business_gateway=gateway,  # type: ignore[arg-type]
        confirmation_id="confirmation-a",
    )
    with (
        patch.object(OrderRepository, "get_by_order_id", new_callable=AsyncMock) as order_lookup,
        patch.object(TicketRepository, "get_by_idempotency_key", new_callable=AsyncMock) as ticket_lookup,
        patch.object(TicketRepository, "create", new_callable=AsyncMock) as create,
    ):
        order_lookup.return_value = SimpleNamespace(order_id="209912310001")
        ticket_lookup.return_value = None
        create.return_value = SimpleNamespace(id="ticket-a", status="open", category="refund")
        await create_refund_case(
            {"order_id": "209912310001", "reason": "损坏", "refund_type": "refund_only"},
            context,
        )
        assert create.await_args.kwargs["idempotency_key"] == "refund:confirmation-a"


@pytest.mark.asyncio
async def test_same_confirmation_returns_existing_ticket_without_second_insert() -> None:
    gateway = BusinessGateway(object())  # type: ignore[arg-type]
    existing = SimpleNamespace(
        id="ticket-a", tenant_id="tenant-a", user_id="user-a", status="open",
        category="refund", detail="损坏", metadata_json={"order_id": "209912310001"},
    )
    with (
        patch.object(OrderRepository, "get_by_order_id", new_callable=AsyncMock) as order_lookup,
        patch.object(TicketRepository, "get_by_idempotency_key", new_callable=AsyncMock) as ticket_lookup,
        patch.object(TicketRepository, "create", new_callable=AsyncMock) as create,
    ):
        order_lookup.return_value = SimpleNamespace(order_id="209912310001")
        ticket_lookup.return_value = existing
        result = await gateway.create_refund_case(
            tenant_id="tenant-a", user_id="user-a", conversation_id="conversation-a",
            order_id="209912310001", reason="损坏", confirmation_id="confirmation-a",
        )
        assert result == {"ticket_id": "ticket-a", "status": "open", "category": "refund"}
        create.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmation_reuse_for_different_order_is_rejected() -> None:
    gateway = BusinessGateway(object())  # type: ignore[arg-type]
    existing = SimpleNamespace(
        id="ticket-a", tenant_id="tenant-a", user_id="user-a", status="open",
        category="refund", detail="损坏", metadata_json={"order_id": "209912310001"},
    )
    with (
        patch.object(OrderRepository, "get_by_order_id", new_callable=AsyncMock) as order_lookup,
        patch.object(TicketRepository, "get_by_idempotency_key", new_callable=AsyncMock) as ticket_lookup,
        patch.object(TicketRepository, "create", new_callable=AsyncMock) as create,
    ):
        order_lookup.return_value = SimpleNamespace(order_id="209912310002")
        ticket_lookup.return_value = existing
        with pytest.raises(AppError) as error:
            await gateway.create_refund_case(
                tenant_id="tenant-a", user_id="user-a", conversation_id="conversation-a",
                order_id="209912310002", reason="损坏", confirmation_id="confirmation-a",
            )
        assert error.value.status_code == 409
        create.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmation_reuse_with_changed_reason_is_rejected() -> None:
    gateway = BusinessGateway(object())  # type: ignore[arg-type]
    existing = SimpleNamespace(
        id="ticket-a", tenant_id="tenant-a", user_id="user-a", status="open",
        category="refund", detail="商品损坏", metadata_json={"order_id": "209912310001"},
    )
    with (
        patch.object(OrderRepository, "get_by_order_id", new_callable=AsyncMock) as order_lookup,
        patch.object(TicketRepository, "get_by_idempotency_key", new_callable=AsyncMock) as ticket_lookup,
        patch.object(TicketRepository, "create", new_callable=AsyncMock) as create,
    ):
        order_lookup.return_value = SimpleNamespace(order_id="209912310001")
        ticket_lookup.return_value = existing
        with pytest.raises(AppError) as error:
            await gateway.create_refund_case(
                tenant_id="tenant-a", user_id="user-a", conversation_id="conversation-a",
                order_id="209912310001", reason="想换一个退款理由",
                confirmation_id="confirmation-a",
            )
        assert error.value.status_code == 409
        create.assert_not_awaited()
