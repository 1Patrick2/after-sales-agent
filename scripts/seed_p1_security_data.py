"""Insert two isolated P1 authorization demo orders, never update old data."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from sqlalchemy import select


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from customer_service_app.infrastructure.db.models import Order  # noqa: E402
from customer_service_app.infrastructure.db.session import (  # noqa: E402
    dispose_engine,
    session_context,
)


async def insert_security_orders(session, *, order_a: str, order_b: str) -> None:
    """Check both IDs before inserting either synthetic order."""
    ids = (order_a, order_b)
    if any(re.fullmatch(r"\d{8,24}", order_id) is None for order_id in ids):
        raise ValueError("Each order ID must contain 8 to 24 digits")
    if order_a == order_b:
        raise ValueError("Order IDs must differ")

    for order_id in ids:
        result = await session.execute(select(Order).where(Order.order_id == order_id))
        if result.scalar_one_or_none() is not None:
            raise ValueError(f"Order {order_id} already exists; no records were inserted")

    for tenant_id, user_id, order_id in (
        ("p1-tenant-a", "p1-customer-a", order_a),
        ("p1-tenant-b", "p1-customer-b", order_b),
    ):
        session.add(
            Order(
                tenant_id=tenant_id,
                user_id=user_id,
                order_id=order_id,
                status="shipped",
                logistics_company="模拟物流",
                tracking_number=f"P1{order_id}",
                metadata_json={"amount": 199, "fixture": "p1_security_demo"},
            )
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Insert two P1-only security demo orders")
    parser.add_argument("order_a")
    parser.add_argument("order_b")
    args = parser.parse_args()
    try:
        async with session_context() as session:
            await insert_security_orders(session, order_a=args.order_a, order_b=args.order_b)
            await session.commit()
        print(json.dumps({"order_a": args.order_a, "order_b": args.order_b}))
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
