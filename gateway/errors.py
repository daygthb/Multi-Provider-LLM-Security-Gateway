from typing import Any


class GatewayError(Exception):
    """Public, sanitized errors. Never construct with upstream content."""

    def __init__(
        self, status: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}

    def payload(self, correlation_id: str) -> dict[str, Any]:
        return {
            "error": {
                "message": self.message,
                "type": self.code,
                "code": self.code,
                "correlation_id": correlation_id,
            }
        }


class RoutingError(GatewayError):
    def __init__(
        self, charged_tokens: int, cost: float, fallbacks: int, provider: str | None
    ) -> None:
        super().__init__(
            503, "no_eligible_provider", "No healthy provider within request cost limit"
        )
        self.charged_tokens = charged_tokens
        self.cost = cost
        self.fallbacks = fallbacks
        self.provider = provider
