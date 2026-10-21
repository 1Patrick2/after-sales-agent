"""Optional, read-only JWT checks against the existing local demo services.

Run only with P1_LIVE_AUTH_TEST=1 and two P0 fixture IDs in the environment.
The app is created in-process with SECURITY_ENABLED=true; the running API and
its .env remain unchanged.
"""

import os

import pytest
from fastapi.testclient import TestClient

from customer_service_app.core.config import get_settings
from customer_service_app.core.security import create_access_token
from customer_service_app.main import create_app


@pytest.mark.skipif(os.getenv("P1_LIVE_AUTH_TEST") != "1", reason="local demo services only")
def test_enabled_auth_enforces_owner_and_tenant_on_real_routes() -> None:
    settings = get_settings()
    confirmation_id = os.environ["P1_CONFIRMATION_ID"]
    thread_id = os.environ["P1_THREAD_ID"]
    assert settings.security_enabled is True
    assert settings.jwt_secret_key

    def token(subject: str, tenant_id: str, roles: list[str]) -> dict[str, str]:
        value = create_access_token(
            subject, settings, extra={"tenant_id": tenant_id, "roles": roles}
        )
        return {"Authorization": f"Bearer {value}"}

    with TestClient(create_app()) as client:
        base = f"/api/v1/confirmations/{confirmation_id}"
        owner = client.get(
            base,
            params={"tenant_id": "default", "user_id": "p0_acceptance"},
            headers=token("p0_acceptance", "default", ["customer"]),
        )
        assert owner.status_code == 200
        assert owner.json()["user_id"] == "p0_acceptance"

        no_token = client.get(base, params={"tenant_id": "default", "user_id": "p0_acceptance"})
        assert no_token.status_code == 401

        bad_token = client.get(
            base, params={"tenant_id": "default", "user_id": "p0_acceptance"},
            headers={"Authorization": "Bearer invalid"},
        )
        assert bad_token.status_code == 403

        wrong_user = client.get(
            base, params={"tenant_id": "default", "user_id": "p0_acceptance"},
            headers=token("other-customer", "default", ["customer"]),
        )
        assert wrong_user.status_code == 403

        wrong_tenant = client.get(
            base, params={"tenant_id": "default", "user_id": "p0_acceptance"},
            headers=token("p0_acceptance", "foreign-tenant", ["customer"]),
        )
        assert wrong_tenant.status_code == 403

        foreign_approval = client.post(
            f"{base}/approve",
            json={"tenant_id": "default", "user_id": "p1_foreign_customer"},
            headers=token("p1_foreign_customer", "default", ["customer"]),
        )
        assert foreign_approval.status_code == 404
        assert foreign_approval.json()["code"] == "confirmation_not_found"

        foreign_rejection = client.post(
            f"{base}/reject",
            json={"tenant_id": "default", "user_id": "p1_foreign_customer"},
            headers=token("p1_foreign_customer", "default", ["customer"]),
        )
        assert foreign_rejection.status_code == 404
        assert foreign_rejection.json()["code"] == "confirmation_not_found"

        cross_tenant_chat = client.post(
            "/api/v1/chat",
            json={"tenant_id": "default", "user_id": "p0_acceptance", "question": "你好"},
            headers=token("p0_acceptance", "foreign-tenant", ["customer"]),
        )
        assert cross_tenant_chat.status_code == 403

        graph = client.get(
            f"/api/v1/graph/threads/{thread_id}",
            headers=token("foreign-operator", "foreign-tenant", ["operator"]),
        )
        assert graph.status_code == 403
        _check_customer_chat(client, settings)


def _check_customer_chat(client: TestClient, settings) -> None:
    """The real LLM/tool path must use the JWT principal, not a guessed order owner."""
    def token(user_id: str, tenant_id: str = "default") -> dict[str, str]:
        value = create_access_token(
            user_id, settings, extra={"tenant_id": tenant_id, "roles": ["customer"]}
        )
        return {"Authorization": f"Bearer {value}"}

    question = "请查询订单 202610210003 的当前状态。"
    owned = client.post(
        "/api/v1/chat",
        json={"tenant_id": "default", "user_id": "p0_acceptance", "question": question},
        headers={**token("p0_acceptance"), "Idempotency-Key": "p1-owned-read-003"},
    )
    assert owned.status_code == 200
    assert any(
        item["name"] == "query_order_status" and item["payload"].get("found") is True
        for item in owned.json()["tool_results"]
    )

    foreign = client.post(
        "/api/v1/chat",
        json={"tenant_id": "default", "user_id": "p1_foreign_customer", "question": question},
        headers={**token("p1_foreign_customer"), "Idempotency-Key": "p1-foreign-read-003"},
    )
    assert foreign.status_code == 200
    assert any(
        item["name"] == "query_order_status" and item["payload"].get("found") is False
        for item in foreign.json()["tool_results"]
    )

    other_tenant_question = "请查询订单 202610210102 的当前状态。"
    wrong_tenant_order = client.post(
        "/api/v1/chat",
        json={
            "tenant_id": "p1-tenant-a", "user_id": "p1-customer-a",
            "question": other_tenant_question,
        },
        headers={**token("p1-customer-a", "p1-tenant-a"), "Idempotency-Key": "p1-cross-tenant-read-102"},
    )
    assert wrong_tenant_order.status_code == 200
    assert any(
        item["name"] == "query_order_status" and item["payload"].get("found") is False
        for item in wrong_tenant_order.json()["tool_results"]
    )

    right_tenant_order = client.post(
        "/api/v1/chat",
        json={
            "tenant_id": "p1-tenant-b", "user_id": "p1-customer-b",
            "question": other_tenant_question,
        },
        headers={**token("p1-customer-b", "p1-tenant-b"), "Idempotency-Key": "p1-own-tenant-read-102"},
    )
    assert right_tenant_order.status_code == 200
    assert any(
        item["name"] == "query_order_status" and item["payload"].get("found") is True
        for item in right_tenant_order.json()["tool_results"]
    )


@pytest.mark.skipif(os.getenv("P1_AUTH_WRITE_TEST") != "1", reason="requires a fresh local demo order")
def test_authenticated_customer_completes_refund_confirmation_once() -> None:
    """Run once per fresh P1 order; this intentionally creates one demo support ticket."""
    settings = get_settings()
    order_id = os.environ["P1_AUTH_WRITE_ORDER_ID"]
    assert settings.security_enabled is True
    token = create_access_token(
        "p1-customer-a", settings,
        extra={"tenant_id": "p1-tenant-a", "roles": ["customer"]},
    )
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app()) as client:
        started = client.post(
            "/api/v1/chat",
            json={
                "tenant_id": "p1-tenant-a", "user_id": "p1-customer-a",
                "question": f"请查询订单 {order_id} 的状态，并提交退款申请，原因是尺寸不合适。",
            },
            headers={**headers, "Idempotency-Key": f"p1-auth-write-{order_id}"},
        )
        assert started.status_code == 200
        pending = started.json()["pending_confirmation"]
        assert started.json()["status"] == "waiting_confirmation"
        assert pending["tool_name"] == "create_refund_case"
        assert pending["arguments"]["order_id"] == order_id

        confirmation_id = pending["id"]
        approved = client.post(
            f"/api/v1/confirmations/{confirmation_id}/approve",
            json={"tenant_id": "p1-tenant-a", "user_id": "p1-customer-a"},
            headers=headers,
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "executed"
        assert approved.json()["graph_status"] == "completed"
        assert any(
            item["name"] == "create_refund_case"
            and item["payload"]["result"].get("ticket_id")
            for item in approved.json()["tool_results"]
        )

        duplicate = client.post(
            f"/api/v1/confirmations/{confirmation_id}/approve",
            json={"tenant_id": "p1-tenant-a", "user_id": "p1-customer-a"},
            headers=headers,
        )
        assert duplicate.status_code == 409
