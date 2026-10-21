"""Read-only post-run P2 refund audit; confirms failed prompts did not write tickets."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from customer_service_app.infrastructure.db.models import PendingAction, SupportTicket
from customer_service_app.infrastructure.db.session import dispose_engine, session_context

from scripts.evaluate_agent import TENANT_ID, USER_ID, load_cases


ROOT = Path(__file__).resolve().parents[1]


async def audit() -> list[dict]:
    cases = [case for case in load_cases(ROOT / "evals" / "agent_cases.jsonl") if case["category"] == "refund"]
    async with session_context() as session:
        tickets = (
            await session.execute(select(SupportTicket).where(
                SupportTicket.tenant_id == TENANT_ID,
                SupportTicket.user_id == USER_ID,
                SupportTicket.category == "refund",
            ))
        ).scalars().all()
        actions = (
            await session.execute(select(PendingAction).where(
                PendingAction.tenant_id == TENANT_ID,
                PendingAction.user_id == USER_ID,
                PendingAction.tool_name == "create_refund_case",
            ))
        ).scalars().all()
    rows = []
    for case in cases:
        order_id = case["order_id"]
        matching_tickets = [item for item in tickets if (item.metadata_json or {}).get("order_id") == order_id]
        matching_actions = [item for item in actions if (item.arguments_json or {}).get("order_id") == order_id]
        rows.append({
            "case_id": case["case_id"], "order_id": order_id,
            "refund_ticket_count": len(matching_tickets),
            "ticket_ids": [item.id for item in matching_tickets],
            "confirmation_statuses": [item.status for item in matching_actions],
            "confirmation_ids": [item.id for item in matching_actions],
        })
    return rows


async def main() -> None:
    try:
        rows = await audit()
        path = ROOT / "reports" / "p2_refund_db_audit.json"
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps([{
            "case_id": row["case_id"],
            "refund_ticket_count": row["refund_ticket_count"],
            "confirmation_statuses": row["confirmation_statuses"],
        } for row in rows], ensure_ascii=False))
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
