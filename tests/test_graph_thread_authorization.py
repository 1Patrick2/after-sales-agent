"""HTTP-level JWT authorization at the sanitized Graph snapshot boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from customer_service_app.api.dependencies import get_customer_service_agent, get_db_session
from customer_service_app.api.routes_graph import router
from customer_service_app.core.config import Settings, get_settings
from customer_service_app.core.exceptions import AppError
from customer_service_app.core.security import create_access_token
from customer_service_app.domain.schemas import GraphStateView
from customer_service_app.infrastructure.db.repositories import AgentRunRepository


TEST_SETTINGS = Settings(
    security_enabled=True,
    jwt_secret_key="p1-local-test-secret-not-for-deployment",
)


def _client(*, run_id: str = "run-b") -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.add_exception_handler(
        AppError,
        lambda _, exc: JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        ),
    )
    agent = SimpleNamespace(
        graph_state=AsyncMock(return_value=GraphStateView(
            thread_id="thread-b", status="waiting_confirmation",
            values={"run_id": run_id, "pending_confirmation": {"id": "confirm-b"}},
        ))
    )
    app.dependency_overrides[get_settings] = lambda: TEST_SETTINGS
    app.dependency_overrides[get_customer_service_agent] = lambda: agent
    app.dependency_overrides[get_db_session] = lambda: object()
    return TestClient(app)


def _bearer(*, subject: str, tenant_id: str, roles: list[str]) -> dict[str, str]:
    token = create_access_token(
        subject, TEST_SETTINGS, extra={"tenant_id": tenant_id, "roles": roles}
    )
    return {"Authorization": f"Bearer {token}"}


def test_foreign_tenant_operator_cannot_read_graph_snapshot() -> None:
    """A sanitized snapshot must still be authorized against its persisted run owner."""
    with patch.object(AgentRunRepository, "get_run", new_callable=AsyncMock) as get_run:
        get_run.return_value = SimpleNamespace(tenant_id="tenant-b", user_id="user-b")
        response = _client().get(
            "/api/v1/graph/threads/thread-b",
            headers=_bearer(subject="operator-a", tenant_id="tenant-a", roles=["operator"]),
        )

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_graph_snapshot_requires_bearer_token() -> None:
    response = _client().get("/api/v1/graph/threads/thread-b")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_invalid_bearer_token_cannot_read_graph_snapshot() -> None:
    response = _client().get(
        "/api/v1/graph/threads/thread-b", headers={"Authorization": "Bearer invalid-token"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_customer_role_cannot_read_operator_graph_snapshot() -> None:
    response = _client().get(
        "/api/v1/graph/threads/thread-b",
        headers=_bearer(subject="user-b", tenant_id="tenant-b", roles=["customer"]),
    )

    assert response.status_code == 403


def test_same_tenant_operator_can_read_graph_snapshot() -> None:
    with patch.object(AgentRunRepository, "get_run", new_callable=AsyncMock) as get_run:
        get_run.return_value = SimpleNamespace(tenant_id="tenant-b", user_id="user-b")
        response = _client().get(
            "/api/v1/graph/threads/thread-b",
            headers=_bearer(subject="operator-b", tenant_id="tenant-b", roles=["operator"]),
        )

    assert response.status_code == 200
    assert response.json()["values"]["run_id"] == "run-b"


def test_graph_snapshot_without_a_persisted_owner_is_not_disclosed() -> None:
    with patch.object(AgentRunRepository, "get_run", new_callable=AsyncMock) as get_run:
        get_run.return_value = None
        response = _client(run_id="missing-run").get(
            "/api/v1/graph/threads/thread-b",
            headers=_bearer(subject="operator-b", tenant_id="tenant-b", roles=["operator"]),
        )

    assert response.status_code == 404
