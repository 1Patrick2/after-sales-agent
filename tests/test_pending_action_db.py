import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from customer_service_app.infrastructure.db.repositories import PendingActionRepository
from customer_service_app.infrastructure.db.session import dispose_engine, session_context


@pytest.mark.skipif(os.getenv("P0_DB_TEST") != "1", reason="requires local demo MySQL")
@pytest.mark.asyncio
async def test_new_pending_action_has_loaded_created_at_after_flush() -> None:
    """The API must serialize a freshly flushed confirmation without async lazy I/O."""
    try:
        async with session_context() as session:
            action = await PendingActionRepository(session).create(
                tenant_id="default",
                user_id="p0_acceptance",
                conversation_id=None,
                action_type="refund",
                tool_name="create_refund_case",
                arguments={"order_id": "202610210001", "reason": "test"},
                confirmation_prompt="test",
                idempotency_key=f"p0-db-test:{uuid4()}",
            )
            assert action.created_at is not None
            created_at = action.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            assert abs((datetime.now(timezone.utc) - created_at).total_seconds()) < 30
            await session.rollback()
    finally:
        await dispose_engine()


@pytest.mark.skipif(os.getenv("P0_DB_TEST") != "1", reason="requires local demo MySQL")
@pytest.mark.asyncio
async def test_claim_for_approval_handles_mysql_naive_expiry() -> None:
    """An action reloaded after an API restart must be claimable exactly once."""
    try:
        async with session_context() as session:
            repo = PendingActionRepository(session)
            action = await repo.create(
                tenant_id="default",
                user_id="p0_acceptance",
                conversation_id=None,
                action_type="refund",
                tool_name="create_refund_case",
                arguments={"order_id": "202610210002", "reason": "test"},
                confirmation_prompt="test",
                idempotency_key=f"p0-db-test:{uuid4()}",
                expire_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
            await session.refresh(action)

            claimed = await repo.claim_for_approval(
                tenant_id="default",
                user_id="p0_acceptance",
                action_id=action.id,
                now=datetime.now(timezone.utc),
            )

            assert claimed is True
            await session.rollback()
    finally:
        await dispose_engine()
