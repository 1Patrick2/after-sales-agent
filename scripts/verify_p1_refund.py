"""Read-only cross-check of one synthetic refund order in the local demo database."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from customer_service_app.infrastructure.db.models import PendingAction, SupportTicket  # noqa: E402
from customer_service_app.infrastructure.db.session import dispose_engine, session_context  # noqa: E402


async def verify(*, tenant_id: str, user_id: str, order_id: str) -> dict:
    async with session_context() as session:
        tickets = (
            await session.execute(select(SupportTicket).where(
                SupportTicket.tenant_id == tenant_id,
                SupportTicket.user_id == user_id,
                SupportTicket.category == "refund",
            ))
        ).scalars().all()
        actions = (
            await session.execute(select(PendingAction).where(
                PendingAction.tenant_id == tenant_id,
                PendingAction.user_id == user_id,
                PendingAction.tool_name == "create_refund_case",
            ))
        ).scalars().all()
        matching_tickets = [
            ticket for ticket in tickets
            if (ticket.metadata_json or {}).get("order_id") == order_id
        ]
        matching_actions = [
            action for action in actions
            if (action.arguments_json or {}).get("order_id") == order_id
        ]
        return {
            "order_id": order_id,
            "refund_ticket_count": len(matching_tickets),
            "tickets": [
                {"id": item.id, "status": item.status, "idempotency_key": item.idempotency_key}
                for item in matching_tickets
            ],
            "confirmations": [
                {"id": item.id, "status": item.status, "thread_id": item.langgraph_thread_id}
                for item in matching_actions
            ],
        }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id")
    parser.add_argument("user_id")
    parser.add_argument("order_id")
    args = parser.parse_args()
    try:
        print(json.dumps(await verify(
            tenant_id=args.tenant_id, user_id=args.user_id, order_id=args.order_id,
        ), ensure_ascii=False))
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
