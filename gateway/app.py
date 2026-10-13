import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST
from redis.asyncio import Redis
from starlette.exceptions import HTTPException

from gateway.auth import IdentityStore, KeyStore
from gateway.errors import GatewayError, RoutingError
from gateway.middleware import SecurityMiddleware
from gateway.models import ChatRequest, KeyIdentity
from gateway.observability import Metrics
from gateway.policy import PolicyEngine
from gateway.providers import ProviderConfig, load_providers
from gateway.quota import MemoryQuota, Quota, RedisQuota
from gateway.redis_auth import RedisKeyStore
from gateway.routing import RoutedCompletion, Router
from gateway.settings import Settings


@dataclass
class Services:
    store: IdentityStore
    quota: Quota
    policy: PolicyEngine
    router: Router
    metrics: Metrics
    semaphore: asyncio.Semaphore


def services(request: Request) -> Services:
    value: Services = request.app.state.services
    return value


async def authenticate(
    request: Request, deps: Annotated[Services, Depends(services)]
) -> KeyIdentity:
    value = request.headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 256:
        raise GatewayError(
            401, "invalid_api_key", "Bearer API key required", {"WWW-Authenticate": "Bearer"}
        )
    key = await deps.store.authenticate(token)
    request.state.audit["tenant"] = key.tenant
    return key


async def operator(key: Annotated[KeyIdentity, Depends(authenticate)]) -> KeyIdentity:
    if "operator" not in key.permissions:
        raise GatewayError(403, "permission_denied", "Operator permission required")
    return key


def create_app(
    settings: Settings | None = None,
    *,
    store: IdentityStore | None = None,
    quota: Quota | None = None,
    client: httpx.AsyncClient | None = None,
    configs: list[ProviderConfig] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    metrics = Metrics()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        identity_store: IdentityStore = store or (
            KeyStore(settings.database)
            if settings.identity_backend == "sqlite"
            else RedisKeyStore(
                Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
            )
        )
        await identity_store.initialize()
        upstream = client or httpx.AsyncClient(
            follow_redirects=False, trust_env=False, limits=httpx.Limits(max_connections=128)
        )
        quotas: Quota = quota or (
            MemoryQuota()
            if settings.quota_backend == "memory"
            else RedisQuota(
                Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
            )
        )
        router = Router(
            configs if configs is not None else load_providers(settings.providers_file),
            upstream,
            settings,
        )
        router.observe_attempt = lambda name, duration, success: metrics.latency.labels(
            name, str(success).lower()
        ).observe(duration)
        deps = Services(
            identity_store,
            quotas,
            PolicyEngine(settings.policy_file),
            router,
            metrics,
            asyncio.Semaphore(settings.max_concurrent_requests),
        )
        app.state.services = deps
        await router.check_health()

        async def health_loop() -> None:
            while True:
                await asyncio.sleep(settings.health_interval)
                await router.check_health()

        task = asyncio.create_task(health_loop())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await quotas.close()
            await identity_store.close()
            if client is None:
                await upstream.aclose()

    app = FastAPI(title="Multi Provider LLM Security Gateway", version="0.1.0", lifespan=lifespan)
    app.add_middleware(SecurityMiddleware, settings=settings, metrics=metrics)

    @app.exception_handler(GatewayError)
    async def gateway_error(request: Request, exc: GatewayError) -> JSONResponse:
        request.state.audit["error_code"] = exc.code
        if exc.status == 429:
            metrics.rate.labels(exc.code).inc()
        return JSONResponse(
            exc.payload(request.state.correlation_id), status_code=exc.status, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's default errors echo input, which may contain prompts or secrets.
        return await gateway_error(
            request, GatewayError(422, "invalid_request", "Invalid chat request")
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return await gateway_error(
            request, GatewayError(exc.status_code, "http_error", "Invalid route or method")
        )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready(deps: Annotated[Services, Depends(services)]) -> dict[str, str]:
        await deps.quota.ready()
        if not deps.router.available():
            raise GatewayError(503, "provider_unavailable", "No available providers")
        return {"status": "ready"}

    @app.get("/metrics", dependencies=[Depends(operator)])
    async def prometheus() -> Response:
        return Response(metrics.render(), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @app.get("/operator/summary", dependencies=[Depends(operator)])
    async def summary(deps: Annotated[Services, Depends(services)]) -> dict[str, Any]:
        return {
            "metrics": metrics.summary(),
            "providers": {
                name: {
                    "healthy": circuit.healthy,
                    "circuit_open": circuit.failures >= settings.circuit_threshold,
                }
                for name, circuit in deps.router.states.items()
            },
        }

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(
            Path(__file__).with_name("dashboard.html").read_text("utf-8"),
            headers={
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; "
                "style-src 'self'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'"
            },
        )

    @app.get("/dashboard.js")
    async def dashboard_js() -> Response:
        return Response(
            Path(__file__).with_name("dashboard.js").read_text("utf-8"),
            media_type="text/javascript",
        )

    @app.get("/dashboard.css")
    async def dashboard_css() -> Response:
        return Response(
            Path(__file__).with_name("dashboard.css").read_text("utf-8"), media_type="text/css"
        )

    @app.post("/v1/chat/completions", response_model=None)
    async def chat(
        payload: ChatRequest,
        request: Request,
        key: Annotated[KeyIdentity, Depends(authenticate)],
        deps: Annotated[Services, Depends(services)],
    ) -> JSONResponse | StreamingResponse:
        if "chat" not in key.permissions:
            raise GatewayError(403, "permission_denied", "Chat permission required")
        if payload.model not in key.allowed_models:
            raise GatewayError(403, "model_not_allowed", "Model is not allowed for this API key")
        audit = request.state.audit
        audit["model"] = payload.model
        actions: list[str] = []
        cleaned = payload.model_copy(deep=True)
        # Scan individual messages and their concatenation for cross-message manipulation.
        decisions = [
            deps.policy.inspect(message.content, "request") for message in payload.messages
        ]
        combined = deps.policy.inspect("\n".join(m.content for m in payload.messages), "request")
        audit["risk_score"] = max([d.risk for d in decisions] + [combined.risk])
        audit["policy_rules"] = sorted({rule for d in [*decisions, combined] for rule in d.rules})
        for message, decision in zip(cleaned.messages, decisions, strict=True):
            message.content = decision.text
            actions.append(decision.action)
        rank = {"allow": 0, "warn": 1, "redact": 2, "block": 3}
        audit["policy_decision"] = max([*actions, combined.action], key=lambda a: rank[a])
        remaining = deps.policy.inspect("\n".join(m.content for m in cleaned.messages), "request")
        if remaining.action in {"redact", "block"}:
            # Cross-message matches cannot be safely mapped back to individual role
            # boundaries. Never report redaction while forwarding matched originals.
            audit["policy_decision"] = "block"
        if audit["policy_decision"] == "block":
            metrics.blocked.labels("request").inc()
            raise GatewayError(403, "policy_blocked", "Request blocked by security policy")
        reservation = await deps.quota.reserve(key, deps.router.reservation_size(cleaned, key))
        charged = reservation.reserved
        result: RoutedCompletion
        try:
            async with deps.semaphore:
                result = await deps.router.complete(cleaned, key)
            charged = result.charged_tokens
            completion = result.completion
            audit.update(
                provider=result.provider,
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
                estimated_cost=result.cost,
            )
            metrics.fallback.inc(result.fallbacks)
            metrics.cost.inc(result.cost)
            response_decision = deps.policy.inspect(completion.text, "response")
            audit["risk_score"] = max(audit["risk_score"], response_decision.risk)
            audit["policy_rules"] = sorted(set(audit["policy_rules"] + response_decision.rules))
            if rank[response_decision.action] > rank[audit["policy_decision"]]:
                audit["policy_decision"] = response_decision.action
            if response_decision.action == "block":
                metrics.blocked.labels("response").inc()
                raise GatewayError(502, "response_blocked", "Response blocked by security policy")
            completion.text = response_decision.text
        except RoutingError as exc:
            charged = exc.charged_tokens
            audit.update(provider=exc.provider, estimated_cost=exc.cost)
            metrics.fallback.inc(exc.fallbacks)
            metrics.cost.inc(exc.cost)
            raise
        finally:
            audit["charged_tokens"] = charged
            # Cancellation keeps the full reservation if finalization itself is interrupted.
            await deps.quota.finalize(reservation, charged)
        base: dict[str, Any] = {
            "id": "chatcmpl-" + uuid4().hex,
            "created": int(time.time()),
            "model": payload.model,
        }
        usage = {
            "prompt_tokens": completion.prompt_tokens,
            "completion_tokens": completion.completion_tokens,
            "total_tokens": completion.total_tokens,
        }
        headers = {**reservation.headers, "x-policy-action": audit["policy_decision"]}
        if not payload.stream:
            return JSONResponse(
                {
                    **base,
                    "object": "chat.completion",
                    "usage": usage,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": completion.text},
                            "finish_reason": completion.finish_reason,
                        }
                    ],
                },
                headers=headers,
            )

        async def events() -> AsyncIterator[str]:
            for offset in range(0, len(completion.text), 32):
                delta: dict[str, str] = {"content": completion.text[offset : offset + 32]}
                if offset == 0:
                    delta["role"] = "assistant"
                yield (
                    "data: "
                    + json.dumps(
                        {
                            **base,
                            "object": "chat.completion.chunk",
                            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                        }
                    )
                    + "\n\n"
                )
            yield (
                "data: "
                + json.dumps(
                    {
                        **base,
                        "object": "chat.completion.chunk",
                        "usage": usage,
                        "choices": [
                            {"index": 0, "delta": {}, "finish_reason": completion.finish_reason}
                        ],
                    }
                )
                + "\n\n"
            )
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream", headers=headers)

    return app
