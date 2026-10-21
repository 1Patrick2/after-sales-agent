from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from customer_service_app.core.exceptions import AppError
from customer_service_app.infrastructure.db.repositories import OrderRepository, TicketRepository
from customer_service_app.services.business_gateway import BusinessGateway


@pytest.mark.asyncio
async def test_local_refund_rejects_order_not_owned_by_caller_without_writing() -> None:
    """A missing or foreign order must never create a refund support ticket."""
    gateway = BusinessGateway(object())  # type: ignore[arg-type]
    ticket = SimpleNamespace(id="ticket-1", status="open", category="refund")

    with (
        patch.object(OrderRepository, "get_by_order_id", new_callable=AsyncMock) as lookup,
        patch.object(TicketRepository, "create", new_callable=AsyncMock) as create,
    ):
        lookup.return_value = None
        create.return_value = ticket

        with pytest.raises(AppError) as error:
            await gateway.create_refund_case(
                tenant_id="tenant-a",
                user_id="caller",
                conversation_id="conversation-1",
                order_id="209912310001",
                reason="商品损坏",
            )

        assert error.value.status_code == 404
        assert error.value.code == "order_not_found"
        lookup.assert_awaited_once_with(
            tenant_id="tenant-a", user_id="caller", order_id="209912310001"
        )
        create.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_refund_keeps_owned_order_write_path() -> None:
    gateway = BusinessGateway(object())  # type: ignore[arg-type]
    ticket = SimpleNamespace(id="ticket-1", status="open", category="refund")

    with (
        patch.object(OrderRepository, "get_by_order_id", new_callable=AsyncMock) as lookup,
        patch.object(TicketRepository, "create", new_callable=AsyncMock) as create,
    ):
        lookup.return_value = SimpleNamespace(order_id="209912310001")
        create.return_value = ticket

        result = await gateway.create_refund_case(
            tenant_id="tenant-a",
            user_id="caller",
            conversation_id="conversation-1",
            order_id="209912310001",
            reason="商品损坏",
        )

        assert result == {"ticket_id": "ticket-1", "status": "open", "category": "refund"}
        lookup.assert_awaited_once_with(
            tenant_id="tenant-a", user_id="caller", order_id="209912310001"
        )
        create.assert_awaited_once()


@pytest.mark.asyncio
async def test_refund_metadata_cannot_replace_verified_order_id() -> None:
    gateway = BusinessGateway(object())  # type: ignore[arg-type]
    with (
        patch.object(OrderRepository, "get_by_order_id", new_callable=AsyncMock) as lookup,
        patch.object(TicketRepository, "create", new_callable=AsyncMock) as create,
    ):
        lookup.return_value = SimpleNamespace(order_id="209912310001")
        create.return_value = SimpleNamespace(id="ticket-1", status="open", category="refund")

        await gateway.create_refund_case(
            tenant_id="tenant-a", user_id="caller", conversation_id="conversation-1",
            order_id="209912310001", reason="商品损坏",
            metadata={"order_id": "foreign-order", "refund_type": "return_refund"},
        )

        assert create.await_args.kwargs["metadata"]["order_id"] == "209912310001"
