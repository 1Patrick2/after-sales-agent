from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from jose import JWTError, jwt
from mcp.server.auth.provider import AccessToken

from after_sales_mcp.config import get_settings


class ServiceTokenVerifier:
    """验证主服务访问 MCP HTTP 端点的服务 JWT。"""

    def __init__(self, secret: str, issuer: str, audience: str = "", required_scope: str = "mcp:invoke"):
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self._required_scope = required_scope

    async def verify_token(self, token: str) -> AccessToken | None:
        """返回 MCP SDK 需要的 AccessToken，验证失败时返回 None。"""

        try:
            decode_kwargs: dict[str, Any] = {
                "issuer": self._issuer,
                "algorithms": ["HS256"],
            }
            if self._audience:
                decode_kwargs["audience"] = self._audience
            claims = jwt.decode(token, self._secret, **decode_kwargs)
        except JWTError:
            return None

        raw_scope = claims.get("scope", "")
        scopes = raw_scope.split() if isinstance(raw_scope, str) else list(raw_scope or [])
        if self._required_scope not in scopes:
            return None
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            return None
        return AccessToken(
            token=token,
            client_id=str(claims.get("client_id", subject)),
            scopes=scopes,
            expires_at=int(claims["exp"]) if claims.get("exp") else None,
            subject=subject,
            claims=claims,
        )


def sign_call_context(
    *,
    secret: str,
    tool_name: str,
    tenant_id: str,
    user_id: str,
    expires_at: int,
) -> str:
    """Sign the end-user context attached to one MCP tool call."""

    payload = _call_context_payload(
        tool_name=tool_name,
        tenant_id=tenant_id,
        user_id=user_id,
        expires_at=expires_at,
    )
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_call_context(
    *,
    context: dict[str, Any],
    tool_name: str,
    tenant_id: str,
    user_id: str,
) -> None:
    """Verify tenant/user/tool metadata signed by the trusted Agent service."""

    settings = get_settings()
    if not settings.call_signing_secret:
        raise ValueError("MCP call signing secret is not configured")

    if (
        context.get("tenant_id") != tenant_id
        or context.get("user_id") != user_id
        or context.get("tool_name") != tool_name
    ):
        raise ValueError("MCP call context does not match tool arguments")

    expires_at = context.get("expires_at")
    signature = context.get("signature")
    if not isinstance(expires_at, int) or expires_at < int(time.time()):
        raise ValueError("MCP call context is expired")
    if not isinstance(signature, str):
        raise ValueError("MCP call context signature is missing")

    expected = sign_call_context(
        secret=settings.call_signing_secret,
        tool_name=tool_name,
        tenant_id=tenant_id,
        user_id=user_id,
        expires_at=expires_at,
    )
    if not hmac.compare_digest(signature, expected):
        raise ValueError("MCP call context signature is invalid")


def _call_context_payload(
    *,
    tool_name: str,
    tenant_id: str,
    user_id: str,
    expires_at: int,
) -> str:
    """Create a stable representation so both services sign identical bytes."""

    return json.dumps(
        {
            "expires_at": expires_at,
            "tenant_id": tenant_id,
            "tool_name": tool_name,
            "user_id": user_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def verify_approval_token(
    *,
    token: str,
    tenant_id: str,
    user_id: str,
    tool_name: str,
) -> dict[str, Any]:
    """Verify that one exact HIL-approved action may execute."""

    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.approval_signing_secret,
            algorithms=["HS256"],
            issuer=settings.approval_issuer,
        )
    except JWTError as exc:
        raise ValueError("Invalid or expired approval token") from exc
    expected = {
        "tenant_id": tenant_id,
        "sub": user_id,
        "tool_name": tool_name,
    }
    for key, value in expected.items():
        if claims.get(key) != value:
            raise ValueError(f"Approval token does not match {key}")
    if not claims.get("confirmation_id"):
        raise ValueError("Approval token does not contain confirmation_id")
    return claims
