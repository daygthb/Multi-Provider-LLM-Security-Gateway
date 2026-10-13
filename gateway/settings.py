from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")
    environment: str = "production"
    database: str = "data/keys.db"
    identity_backend: Literal["sqlite", "redis"] = "redis"
    quota_backend: str = "redis"
    redis_url: str = "redis://localhost:6379/0"
    policy_file: str = "config/policy.yaml"
    providers_file: str = "config/providers.yaml"
    request_timeout: float = Field(default=45, gt=0, le=300)
    upstream_timeout: float = Field(default=10, gt=0, le=120)
    retries: int = Field(default=1, ge=0, le=3)
    backoff: float = Field(default=0.2, ge=0, le=5)
    circuit_threshold: int = Field(default=3, ge=1)
    circuit_reset: float = Field(default=30, gt=0)
    max_request_bytes: int = Field(default=65536, ge=1024)
    max_response_bytes: int = Field(default=131072, ge=1024)
    max_concurrent_requests: int = Field(default=64, ge=1)
    health_interval: float = Field(default=15, gt=0)

    @model_validator(mode="after")
    def validate_backend(self) -> "Settings":
        if self.quota_backend not in {"redis", "memory"}:
            raise ValueError("quota_backend must be redis or memory")
        if self.quota_backend == "memory" and self.environment not in {"demo", "test"}:
            raise ValueError("memory quotas require explicit demo or test environment")
        return self
