from types import SimpleNamespace

import pytest


class FakeSession:
    def __init__(self, existing: list[object | None]):
        self.existing = list(existing)
        self.added: list[object] = []

    async def execute(self, statement):
        return SimpleNamespace(scalar_one_or_none=lambda: self.existing.pop(0))

    def add(self, order: object) -> None:
        self.added.append(order)


@pytest.mark.asyncio
async def test_p1_seed_creates_distinct_tenant_owned_demo_orders() -> None:
    from scripts.seed_p1_security_data import insert_security_orders

    session = FakeSession([None, None])
    await insert_security_orders(session, order_a="202610210101", order_b="202610210102")

    assert [(item.tenant_id, item.user_id, item.order_id) for item in session.added] == [
        ("p1-tenant-a", "p1-customer-a", "202610210101"),
        ("p1-tenant-b", "p1-customer-b", "202610210102"),
    ]


@pytest.mark.asyncio
async def test_p1_seed_aborts_before_inserting_if_either_id_exists() -> None:
    from scripts.seed_p1_security_data import insert_security_orders

    session = FakeSession([None, object()])
    with pytest.raises(ValueError, match="already exists"):
        await insert_security_orders(session, order_a="202610210101", order_b="202610210102")

    assert session.added == []
