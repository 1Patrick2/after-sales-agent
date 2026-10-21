from types import SimpleNamespace

import pytest


class FakeSession:
    def __init__(self, existing: list[object | None]):
        self.existing = list(existing)
        self.added: list[object] = []
        self.statements: list[object] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(scalar_one_or_none=lambda: self.existing.pop(0))

    def add(self, order: object) -> None:
        self.added.append(order)


@pytest.mark.asyncio
async def test_refund_acceptance_seed_inserts_only_two_unused_orders() -> None:
    from scripts.seed_refund_acceptance_data import insert_orders

    session = FakeSession([None, None])
    await insert_orders(
        session,
        tenant_id="default",
        user_id="p0_acceptance",
        reject_order_id="209912310001",
        approve_order_id="209912310002",
    )

    assert [order.order_id for order in session.added] == ["209912310001", "209912310002"]
    assert all(order.tenant_id == "default" for order in session.added)
    assert all(order.user_id == "p0_acceptance" for order in session.added)
    assert all(order.status == "shipped" for order in session.added)
    assert [set(statement.compile().params.values()) for statement in session.statements] == [
        {"209912310001"},
        {"209912310002"},
    ]


@pytest.mark.asyncio
async def test_refund_acceptance_seed_aborts_without_writes_on_existing_order() -> None:
    from scripts.seed_refund_acceptance_data import insert_orders

    session = FakeSession([None, object()])
    with pytest.raises(ValueError, match="already exists"):
        await insert_orders(
            session,
            tenant_id="default",
            user_id="p0_acceptance",
            reject_order_id="209912310001",
            approve_order_id="209912310002",
        )

    assert session.added == []


@pytest.mark.asyncio
async def test_refund_acceptance_seed_rejects_invalid_ids_before_query() -> None:
    from scripts.seed_refund_acceptance_data import insert_orders

    session = FakeSession([])
    with pytest.raises(ValueError, match="8 to 24 digits"):
        await insert_orders(
            session,
            tenant_id="default",
            user_id="p0_acceptance",
            reject_order_id="bad-order",
            approve_order_id="209912310002",
        )

    assert session.added == []
