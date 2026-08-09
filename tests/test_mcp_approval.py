from __future__ import annotations

from typing import Any

import pytest
from jose import jwt

from customer_service_app.core.config import Settings
from customer_service_app.infrastructure.mcp.approval import (
    build_approval_token,
    build_confirmation_id,
)
from customer_service_app.services.business_gateway import BusinessGateway
from customer_service_app.infrastructure.mcp.client import _build_call_meta


def test_mcp_call_context_is_bound_to_tenant_user_and_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CALL_SIGNING_SECRET", "call-secret")
    monkeypatch.setenv("DATABASE_URL", "mysql+aiomysql://user:password@localhost/db")
    monkeypatch.setenv("APPROVAL_SIGNING_SECRET", "approval-secret")

    from after_sales_mcp.config import get_settings as get_mcp_settings
    from after_sales_mcp.security import verify_call_context

    get_mcp_settings.cache_clear()
    metadata = _build_call_meta(
        secret="call-secret",
        name="query_order_status",
        arguments={"tenant_id": "tenant-a", "user_id": "user-a", "order_id": "o-1"},
        ttl_seconds=60,
    )
    verify_call_context(
        context=metadata,
        tool_name="query_order_status",
        tenant_id="tenant-a",
        user_id="user-a",
    )
    metadata["user_id"] = "user-b"
    with pytest.raises(ValueError, match="signature is invalid"):
        verify_call_context(
            context=metadata,
            tool_name="query_order_status",
            tenant_id="tenant-a",
            user_id="user-b",
        )

    mismatch_metadata = _build_call_meta(
        secret="call-secret",
        name="query_order_status",
        arguments={"tenant_id": "tenant-a", "user_id": "user-b", "order_id": "o-1"},
        ttl_seconds=60,
    )
    with pytest.raises(ValueError, match="does not match"):
        verify_call_context(
            context=mismatch_metadata,
            tool_name="query_order_status",
            tenant_id="tenant-a",
            user_id="user-a",
        )
    get_mcp_settings.cache_clear()


class FakeMCPClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def list_tools(self):  # pragma: no cover - not used in this test
        return []

    async def call_tool(self, *, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"name": name, "arguments": arguments})
        return {"ok": True, "tool": name}

    async def close(self) -> None:  # pragma: no cover - not used in this test
        return None


def test_confirmation_id_is_stable_and_argument_sensitive() -> None:
    first = build_confirmation_id(
        tool_name="create_refund_case",
        tenant_id="tenant-a",
        user_id="u001",
        arguments={"order_id": "o001", "reason": "broken"},
    )
    second = build_confirmation_id(
        tool_name="create_refund_case",
        tenant_id="tenant-a",
        user_id="u001",
        arguments={"reason": "broken", "order_id": "o001"},
    )
    changed = build_confirmation_id(
        tool_name="create_refund_case",
        tenant_id="tenant-a",
        user_id="u001",
        arguments={"order_id": "o002", "reason": "broken"},
    )

    assert first == second
    assert first != changed


def test_approval_token_binds_tool_tenant_user_and_confirmation_id() -> None:
    settings = Settings(
        mcp_approval_signing_secret="test-secret",
        mcp_approval_issuer="test-issuer",
        mcp_approval_token_ttl_seconds=60,
    )
    arguments = {"order_id": "o001", "reason": "broken"}

    token = build_approval_token(
        settings=settings,
        tool_name="create_refund_case",
        tenant_id="tenant-a",
        user_id="u001",
        arguments=arguments,
    )
    claims = jwt.decode(
        token,
        "test-secret",
        algorithms=["HS256"],
        issuer="test-issuer",
    )

    assert claims["tenant_id"] == "tenant-a"
    assert claims["sub"] == "u001"
    assert claims["tool_name"] == "create_refund_case"
    assert claims["confirmation_id"] == build_confirmation_id(
        tool_name="create_refund_case",
        tenant_id="tenant-a",
        user_id="u001",
        arguments=arguments,
    )
    assert claims["jti"]


@pytest.mark.asyncio
async def test_business_gateway_forwards_hil_approval_token_to_mcp() -> None:
    mcp_client = FakeMCPClient()
    gateway = BusinessGateway(
        object(),  # type: ignore[arg-type]
        mcp_client=mcp_client,  # type: ignore[arg-type]
    )

    await gateway.create_refund_case(
        tenant_id="tenant-a",
        user_id="u001",
        conversation_id="c001",
        order_id="o001",
        reason="broken",
        priority="normal",
        approval_token="hil-approved-token",
    )

    assert mcp_client.calls[0]["name"] == "create_refund_case"
    arguments = mcp_client.calls[0]["arguments"]
    assert arguments["approval_token"] == "hil-approved-token"
