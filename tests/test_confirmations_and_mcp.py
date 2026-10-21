from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from customer_service_app.core.config import Settings
from customer_service_app.infrastructure.mcp.client import _normalize_tool_result
from customer_service_app.infrastructure.db.repositories import PendingActionRepository
from customer_service_app.services.confirmation_service import ConfirmationService


def test_pending_action_expiration_uses_configured_ttl() -> None:
    service = ConfirmationService(
        session=object(),  # type: ignore[arg-type]
        settings=Settings(pending_action_ttl_seconds=10),
    )

    expired_action = SimpleNamespace(
        created_at=datetime.now(timezone.utc) - timedelta(seconds=11)
    )
    fresh_action = SimpleNamespace(
        created_at=datetime.now(timezone.utc) - timedelta(seconds=3)
    )

    assert service._is_expired(expired_action) is True  # type: ignore[arg-type]
    assert service._is_expired(fresh_action) is False  # type: ignore[arg-type]


def test_pending_action_expiration_accepts_mysql_naive_utc_expire_at() -> None:
    service = ConfirmationService(
        session=object(),  # type: ignore[arg-type]
        settings=Settings(),
    )
    now = datetime.now(timezone.utc)
    fresh = SimpleNamespace(expire_at=(now + timedelta(minutes=5)).replace(tzinfo=None))
    expired = SimpleNamespace(expire_at=(now - timedelta(minutes=5)).replace(tzinfo=None))

    assert service._is_expired(fresh) is False  # type: ignore[arg-type]
    assert service._is_expired(expired) is True  # type: ignore[arg-type]


def test_mcp_tool_result_prefers_structured_content() -> None:
    result = SimpleNamespace(structured_content={"ticket_id": "t001", "status": "open"})

    assert _normalize_tool_result(result) == {"ticket_id": "t001", "status": "open"}


def test_mcp_tool_result_parses_text_json() -> None:
    result = SimpleNamespace(
        structured_content=None,
        structuredContent=None,
        content=[SimpleNamespace(text='{"found": true, "order_id": "o001"}')],
    )

    assert _normalize_tool_result(result) == {"found": True, "order_id": "o001"}


@pytest.mark.asyncio
async def test_pending_action_claim_allows_only_one_request() -> None:
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(rowcount=1)
    repo = PendingActionRepository(session)

    claimed = await repo.claim_for_approval(
        tenant_id="tenant-a",
        user_id="user-a",
        action_id="action-a",
        now=datetime.now(timezone.utc),
    )

    assert claimed is True
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_action_claim_rejects_losing_request() -> None:
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(rowcount=0)
    repo = PendingActionRepository(session)

    claimed = await repo.claim_for_approval(
        tenant_id="tenant-a",
        user_id="user-a",
        action_id="action-a",
        now=datetime.now(timezone.utc),
    )

    assert claimed is False
    session.flush.assert_awaited_once()
