import json
import logging
from datetime import UTC, datetime
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

audit_logger = logging.getLogger("gateway.audit")


def emit_audit(fields: dict[str, Any]) -> None:
    # Explicit allowlist; request/response bodies and exception strings never enter logs.
    allowed = {
        "correlation_id",
        "tenant",
        "model",
        "provider",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "charged_tokens",
        "policy_decision",
        "policy_rules",
        "risk_score",
        "status",
        "error_code",
        "estimated_cost",
    }
    event = {key: value for key, value in fields.items() if key in allowed}
    event["timestamp"] = datetime.now(UTC).isoformat()
    event["event"] = "llm_gateway_request"
    audit_logger.info(json.dumps(event, separators=(",", ":")))


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "gateway_requests", "Chat requests", ["status"], registry=self.registry
        )
        self.blocked = Counter(
            "gateway_blocked_requests", "Policy blocks", ["direction"], registry=self.registry
        )
        self.rate = Counter(
            "gateway_rate_limit_rejections", "Quota rejections", ["reason"], registry=self.registry
        )
        self.fallback = Counter(
            "gateway_fallback_usage", "Provider fallback selections", registry=self.registry
        )
        self.cost = Counter(
            "gateway_estimated_cost_dollars",
            "Estimated provider cost in USD",
            registry=self.registry,
        )
        self.latency = Histogram(
            "gateway_provider_latency_seconds",
            "Provider attempt duration",
            ["provider", "success"],
            registry=self.registry,
        )
        # Export zero-valued series before the first event so operator views do
        # not silently omit a required metric on a fresh deployment.
        self.requests.labels("200").inc(0)
        for direction in ("request", "response"):
            self.blocked.labels(direction).inc(0)
        for reason in ("rate_limit_exceeded", "budget_exceeded"):
            self.rate.labels(reason).inc(0)

    def render(self) -> bytes:
        return generate_latest(self.registry)

    def summary(self) -> dict[str, float]:
        values: dict[str, float] = {}
        for family in self.registry.collect():
            for sample in family.samples:
                if sample.name.endswith(("_total", "_count", "_sum")):
                    values[sample.name] = values.get(sample.name, 0) + sample.value
        return values
