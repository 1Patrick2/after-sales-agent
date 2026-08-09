from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration owned by the independently deployable MCP service."""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    database_url: str
    host: str = "0.0.0.0"
    port: int = 8100
    approval_signing_secret: str
    approval_issuer: str = "customer-service-agent"
    service_auth_enabled: bool = True
    service_auth_secret: str = ""
    service_auth_issuer: str = "customer-service-agent"
    service_auth_audience: str = ""
    service_auth_required_scope: str = "mcp:invoke"
    service_auth_issuer_url: str = "https://auth.example.com"
    service_auth_resource_url: str = "https://mcp-after-sales.example.com"
    call_signing_secret: str = ""
    call_context_ttl_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
