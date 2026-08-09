from __future__ import annotations

import json
import hashlib
import hmac
import logging
import shlex
import time
from asyncio import Lock
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.types import CallToolResult, ListToolsResult, ReadResourceResult, TextResourceContents, Tool

from customer_service_app.core.config import Settings
from customer_service_app.core.exceptions import ExternalServiceError
from customer_service_app.infrastructure.mcp.base import MCPBusinessClient, MCPToolContract


def build_after_sales_mcp_client(settings: Settings) -> MCPBusinessClient | None:
    """Build the configured after-sales MCP client."""

    if not settings.mcp_after_sales_enabled:
        return None
    if settings.mcp_after_sales_transport == "stdio":
        return StdioMCPBusinessClient(
            command=settings.mcp_after_sales_command,
            args=shlex.split(settings.mcp_after_sales_args),
            timeout_seconds=settings.mcp_timeout_seconds,
            call_signing_secret=settings.require(
                "MCP_CALL_SIGNING_SECRET", settings.mcp_call_signing_secret
            ),
            call_context_ttl_seconds=settings.mcp_call_context_ttl_seconds,
        )
    return StreamableHttpMCPBusinessClient(
        url=settings.mcp_after_sales_url,
        timeout_seconds=settings.mcp_timeout_seconds,
        service_auth_token=(
            settings.require("MCP_SERVICE_AUTH_TOKEN", settings.mcp_service_auth_token)
            if settings.mcp_service_auth_enabled
            else None
        ),
        call_signing_secret=settings.require(
            "MCP_CALL_SIGNING_SECRET", settings.mcp_call_signing_secret
        ),
        call_context_ttl_seconds=settings.mcp_call_context_ttl_seconds,
        contract_cache_ttl_seconds=settings.mcp_tool_contract_cache_ttl_seconds,
    )


class NotConfiguredMCPClient(MCPBusinessClient):
    """Fail explicitly when a mandatory MCP capability has not been configured."""

    async def list_tools(self) -> list[MCPToolContract]:
        return []

    async def call_tool(self, *, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise ExternalServiceError(f"MCP client is not configured for tool: {name}")



class StreamableHttpMCPBusinessClient(MCPBusinessClient):
    """MCP client for an independently deployed Streamable HTTP server."""


    def __init__(
        self,
        *,
        url: str,
        timeout_seconds: int,
        service_auth_token: str | None,
        call_signing_secret: str,
        call_context_ttl_seconds: int,
        contract_cache_ttl_seconds: int,
    ):
        self._url = url
        self._timeout_seconds = timeout_seconds
        self._call_signing_secret = call_signing_secret
        self._call_context_ttl_seconds = call_context_ttl_seconds
        self._contract_cache_ttl_seconds = contract_cache_ttl_seconds
        headers = (
            {"Authorization": f"Bearer {service_auth_token}"}
            if service_auth_token
            else {}
        )
        self._http_client = httpx.AsyncClient(timeout=timeout_seconds, headers=headers)
        self._session: ClientSession | None = None
        self._transport_context: Any = None
        self._session_context: Any = None
        self._session_lock = Lock()
        self._contracts_lock = Lock()
        self._contracts: list[MCPToolContract] | None = None
        self._contracts_loaded_at = 0.0

    async def start(self) -> None:
        """Open one MCP session during application startup and reuse it."""

        if self._session is not None:
            return
        async with self._session_lock:
            if self._session is not None:
                return
            try:
                from mcp.client.streamable_http import streamable_http_client
            except ImportError as exc:
                raise ExternalServiceError(
                    "Python package `mcp` is required for MCP integration"
                ) from exc

            self._transport_context = streamable_http_client(
                self._url,
                http_client=self._http_client,
            )
            read, write, _ = await self._transport_context.__aenter__()
            self._session_context = ClientSession(
                read,
                write,
                read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
            )
            self._session = await self._session_context.__aenter__()
            await self._session.initialize()

    async def _active_session(self) -> ClientSession:
        """Return the initialized session, allowing lazy use outside FastAPI."""

        await self.start()
        if self._session is None:  # pragma: no cover - defensive guard
            raise ExternalServiceError("MCP session is not available")
        return self._session

    def _call_meta(self, *, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Build signed tenant/user context carried in MCP request metadata."""

        return _build_call_meta(
            secret=self._call_signing_secret,
            name=name,
            arguments=arguments,
            ttl_seconds=self._call_context_ttl_seconds,
        )

    async def _close_session(self) -> None:
        """Close the MCP session and transport in reverse order."""

        if self._session_context is not None:
            await self._session_context.__aexit__(None, None, None)
        if self._transport_context is not None:
            await self._transport_context.__aexit__(None, None, None)
        self._session = None
        self._session_context = None
        self._transport_context = None

    async def _refresh_contracts(self, session: ClientSession) -> list[MCPToolContract]:
        """Read tools and governance metadata once per configured TTL."""

        response: ListToolsResult = await session.list_tools()
        contracts = await _read_contracts(session)
        result = _to_contracts(response.tools, contracts)
        self._contracts = result
        self._contracts_loaded_at = time.monotonic()
        return result

    async def list_tools(self) -> list[MCPToolContract]:
        """Discover tools and reuse the contract until its TTL expires."""

        if (
            self._contracts is not None
            and time.monotonic() - self._contracts_loaded_at < self._contract_cache_ttl_seconds
        ):
            return list(self._contracts)

        async with self._contracts_lock:
            if (
                self._contracts is not None
                and time.monotonic() - self._contracts_loaded_at < self._contract_cache_ttl_seconds
            ):
                return list(self._contracts)
            return await self._refresh_contracts(await self._active_session())

    async def call_tool(self, *, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call the shared MCP session with signed end-user context."""

        session = await self._active_session()
        tool_call_result: CallToolResult = await session.call_tool(
            name=name,
            arguments=arguments,
            meta=self._call_meta(name=name, arguments=arguments),
            read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
        )
        return _normalize_tool_result(tool_call_result)

    async def close(self) -> None:
        """Close the MCP session and shared HTTP connection pool."""

        async with self._session_lock:
            await self._close_session()
        await self._http_client.aclose()


class StdioMCPBusinessClient(MCPBusinessClient):
    """Development-only client that starts a local MCP subprocess per operation."""

    def __init__(
        self,
        *,
        command: str,
        args: list[str],
        timeout_seconds: int,
        call_signing_secret: str,
        call_context_ttl_seconds: int,
    ):
        self._command = command
        self._args = args
        self._timeout_seconds = timeout_seconds
        self._call_signing_secret = call_signing_secret
        self._call_context_ttl_seconds = call_context_ttl_seconds

    async def start(self) -> None:
        """Stdio is intentionally started per operation, so startup is a no-op."""

        return None

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        try:
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise ExternalServiceError(
                "Python package `mcp` is required for MCP integration"
            ) from exc

        params = StdioServerParameters(
            command=self._command,
            args=self._args,
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
            ) as session:
                await session.initialize()
                yield session

    async def list_tools(self) -> list[MCPToolContract]:
        """从本地 stdio MCP 子进程发现工具。"""

        async with self._session() as session:
            response = await session.list_tools()
            contracts = await _read_contracts(session)
            return _to_contracts(response.tools, contracts)


    async def call_tool(self, *, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """通过 stdio 传输调用 MCP 工具。"""

        async with self._session() as session:
            result = await session.call_tool(
                name,
                arguments,
                meta=_build_call_meta(
                    secret=self._call_signing_secret,
                    name=name,
                    arguments=arguments,
                    ttl_seconds=self._call_context_ttl_seconds,
                ),
            )
            normalized = _normalize_tool_result(result)
            return normalized



async def _read_contracts(session: ClientSession) -> dict[str, dict[str, Any]]:
    try:
        response: ReadResourceResult = await session.read_resource("after-sales://tool-contracts")
    except Exception as exc:
        logging.info("session.read_resource error: %s", exc)
        return {}

    text_parts = [
        item.text
        for item in response.contents
        if isinstance(item, TextResourceContents) and item.text
    ]
    if not text_parts:
        return {}

    try:
        items = json.loads("\n".join(text_parts))
    except json.JSONDecodeError:
        return {}

    return {
        item["name"]: item
        for item in items
        if isinstance(item, dict) and "name" in item
    }




def _to_contracts(tools: list[Tool], contracts_by_name: dict[str, dict[str, Any]]) -> list[MCPToolContract]:
    result: list[MCPToolContract] = []
    for tool in tools:
        contract = contracts_by_name.get(tool.name, {})
        result.append(MCPToolContract(
            name=tool.name,
            description=tool.description or "",
            parameters=getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {},
            read_only=bool(contract.get("read_only", True)),
            requires_confirmation=bool(contract.get("requires_confirmation", False)),
            risk_level=str(contract.get("risk_level", "low")),
            action_type=str(contract.get("action_type", "tool")),
        ))
    return result


def _normalize_tool_result(result: CallToolResult) -> dict[str, Any]:
    structured_content = getattr(result, "structuredContent", None) or getattr(
        result, "structured_content", None
    )
    if isinstance(structured_content, dict):
        return structured_content

    texts = [
        item.text
        for item in getattr(result, "content", [])
        if getattr(item, "text", None)
    ]
    if not texts:
        return {}

    raw = "\n".join(texts)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"text": raw}
    if isinstance(parsed, dict):
        return parsed
    return {"result": parsed}


def _build_call_meta(
    *,
    secret: str,
    name: str,
    arguments: dict[str, Any],
    ttl_seconds: int,
) -> dict[str, Any]:
    """Create the metadata verified by the independent MCP service."""

    tenant_id = arguments.get("tenant_id")
    user_id = arguments.get("user_id")
    if not isinstance(tenant_id, str) or not isinstance(user_id, str):
        raise ExternalServiceError("MCP arguments must contain tenant_id and user_id")
    expires_at = int(time.time()) + ttl_seconds
    payload = json.dumps(
        {
            "expires_at": expires_at,
            "tenant_id": tenant_id,
            "tool_name": name,
            "user_id": user_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "tool_name": name,
        "expires_at": expires_at,
        "signature": signature,
    }
