import asyncio
import time
from typing import Any
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gateway.errors import GatewayError
from gateway.observability import Metrics, emit_audit
from gateway.settings import Settings


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings, metrics: Metrics) -> None:
        self.app, self.settings, self.metrics = app, settings, metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.monotonic()
        correlation = uuid4().hex
        state = scope.setdefault("state", {})
        state["correlation_id"] = correlation
        audit: dict[str, Any] = {
            "correlation_id": correlation,
            "tenant": None,
            "model": None,
            "provider": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "charged_tokens": 0,
            "policy_decision": "allow",
            "policy_rules": [],
            "risk_score": 0,
            "estimated_cost": 0,
        }
        state["audit"] = audit
        status = 500
        started = False

        async def wrapped_send(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                status, started = message["status"], True
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-correlation-id", correlation.encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (b"cache-control", b"no-store"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        try:
            async with asyncio.timeout(self.settings.request_timeout):
                # Buffer the bounded body before validation, including chunked requests.
                chunks: list[bytes] = []
                size = 0
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    size += len(chunk)
                    if size > self.settings.max_request_bytes:
                        raise GatewayError(413, "request_too_large", "Request body exceeded limit")
                    chunks.append(chunk)
                    if not message.get("more_body", False):
                        break
                consumed = False

                async def replay() -> Message:
                    nonlocal consumed
                    if consumed:
                        return await receive()
                    consumed = True
                    return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

                await self.app(scope, replay, wrapped_send)
        except TimeoutError:
            error = GatewayError(504, "request_timeout", "Gateway request deadline exceeded")
            audit["error_code"] = error.code
            if not started:
                await JSONResponse(error.payload(correlation), status_code=error.status)(
                    scope, receive, wrapped_send
                )
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, GatewayError)
                else GatewayError(503, "service_unavailable", "Gateway service unavailable")
            )
            audit["error_code"] = error.code
            if not started:
                await JSONResponse(
                    error.payload(correlation), status_code=error.status, headers=error.headers
                )(scope, receive, wrapped_send)
        finally:
            if scope["path"] == "/v1/chat/completions":
                audit.update(status=status, latency_ms=round((time.monotonic() - start) * 1000, 3))
                self.metrics.requests.labels(str(status)).inc()
                emit_audit(audit)
