"""Opt-in MySQL claim race; creates only a synthetic confirmation, never a ticket."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from customer_service_app.infrastructure.db.repositories import PendingActionRepository
from customer_service_app.infrastructure.db.session import dispose_engine, session_context


@pytest.mark.skipif(os.getenv("P1_DB_CONCURRENCY_TEST") != "1", reason="requires local demo MySQL")
@pytest.mark.asyncio
async def test_two_sessions_can_claim_same_pending_action_only_once() -> None:
    action_id = ""
    try:
        async with session_context() as session:
            action = await PendingActionRepository(session).create(
                tenant_id="p1-concurrency-test", user_id="synthetic-test-user",
                conversation_id=None, action_type="refund", tool_name="create_refund_case",
                arguments={"order_id": "000000000000", "reason": "synthetic race test"},
                confirmation_prompt="synthetic race test",
                idempotency_key=f"p1-concurrency:{uuid4()}",
                expire_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
            action_id = action.id
            await session.commit()

        async def claim() -> bool:
            async with session_context() as session:
                won = await PendingActionRepository(session).claim_for_approval(
                    tenant_id="p1-concurrency-test", user_id="synthetic-test-user",
                    action_id=action_id, now=datetime.now(timezone.utc),
                )
                await session.commit()
                return won

        outcomes = await asyncio.gather(claim(), claim())
        assert sorted(outcomes) == [False, True]
        async with session_context() as session:
            action = await PendingActionRepository(session).get_owned(
                tenant_id="p1-concurrency-test", user_id="synthetic-test-user",
                action_id=action_id,
            )
            assert action is not None
            assert action.status == "approved"
    finally:
        await dispose_engine()
