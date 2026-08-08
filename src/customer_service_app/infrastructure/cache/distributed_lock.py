from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis

from customer_service_app.core.config import Settings
from customer_service_app.core.exceptions import AppError, ExternalServiceError


_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


class RedisConversationLock:
    """Use a Redis lease to serialize graph mutations for one conversation.

    同一个会话可能因为重试、双击或多端同时发送而并发进入。锁只保护同一个
    tenant/user/conversation（或 thread）范围，不会把整个租户串行化。锁值包含
    随机 owner token，释放和续租都必须先校验 token，避免旧请求误删新请求的锁。
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._redis: redis.Redis | None = None

    @property
    def _client(self) -> redis.Redis:
        if self._redis is None:
            url = self._settings.require("REDIS_URL", self._settings.redis_url)
            self._redis = redis.from_url(url, decode_responses=True)
        return self._redis

    @asynccontextmanager
    async def hold(
        self,
        *,
        tenant_id: str,
        user_id: str,
        conversation_id: str | None,
        thread_id: str | None,
        request_id: str | None,
    ) -> AsyncIterator[None]:
        """Acquire, renew, and safely release one conversation lease."""
        scope = conversation_id or thread_id or request_id or "new-session"
        digest = hashlib.sha256(
            f"{tenant_id}:{user_id}:{scope}".encode("utf-8")
        ).hexdigest()
        key = f"customer-service:conversation-lock:{digest}"
        owner = secrets.token_urlsafe(24)
        ttl = max(int(self._settings.request_lock_ttl_seconds), 10)

        try:
            acquired = await self._client.set(key, owner, nx=True, ex=ttl)
        except Exception as exc:
            raise ExternalServiceError("Conversation lock service is unavailable") from exc
        if not acquired:
            raise AppError(
                "The conversation is being processed; retry later",
                code="conversation_busy",
                status_code=409,
            )

        renew_task = asyncio.create_task(self._renew(key=key, owner=owner, ttl=ttl))
        try:
            yield
        finally:
            renew_task.cancel()
            try:
                await renew_task
            except asyncio.CancelledError:
                pass
            try:
                await self._client.eval(_RELEASE_SCRIPT, 1, key, owner)
            except Exception:
                # TTL 仍会兜底释放；这里不能再覆盖原请求异常。
                pass

    async def _renew(self, *, key: str, owner: str, ttl: int) -> None:
        """续租长时间的 LLM/MCP 请求，旧 owner 失效后不会续到新锁。"""
        interval = max(ttl // 3, 3)
        while True:
            await asyncio.sleep(interval)
            try:
                renewed = await self._client.eval(_RENEW_SCRIPT, 1, key, owner, ttl)
            except Exception:
                return
            if int(renewed or 0) != 1:
                return

    async def close(self) -> None:
        """Close the shared Redis connection pool."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
