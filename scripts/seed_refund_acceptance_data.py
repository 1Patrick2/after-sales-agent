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


async def insert_orders(
    session,
    *,
    tenant_id: str,
    user_id: str,
    reject_order_id: str,
    approve_order_id: str,
) -> None:
    """Insert two isolated demo orders, or leave the database unchanged."""
    order_ids = (reject_order_id, approve_order_id)
    if any(re.fullmatch(r"\d{8,24}", order_id) is None for order_id in order_ids):
        raise ValueError("Each order ID must contain 8 to 24 digits")
    if reject_order_id == approve_order_id:
        raise ValueError("Reject and approve order IDs must differ")

    for order_id in order_ids:
        result = await session.execute(
            select(Order).where(
                Order.order_id == order_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError(f"Order {order_id} already exists; no records were inserted")

    for order_id in order_ids:
        session.add(
            Order(
                tenant_id=tenant_id,
                user_id=user_id,
                order_id=order_id,
                status="shipped",
                logistics_company="模拟物流",
                tracking_number=f"P0{order_id}",
                metadata_json={
                    "amount": 299,
                    "product": "P0 模拟售后测试商品",
                    "after_sale_days": 7,
                    "fixture": "refund_hil_p0",
                },
            )
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Insert two P0-only refund test orders")
    parser.add_argument("reject_order_id")
    parser.add_argument("approve_order_id")
    args = parser.parse_args()

    try:
        async with session_context() as session:
            await insert_orders(
                session,
                tenant_id="default",
                user_id="p0_acceptance",
                reject_order_id=args.reject_order_id,
                approve_order_id=args.approve_order_id,
            )
            await session.commit()
        print(
            json.dumps(
                {
                    "tenant_id": "default",
                    "user_id": "p0_acceptance",
                    "reject_order_id": args.reject_order_id,
                    "approve_order_id": args.approve_order_id,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
