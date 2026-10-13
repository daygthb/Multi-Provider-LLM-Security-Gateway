import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from gateway.errors import GatewayError, RoutingError
from gateway.models import ChatRequest, Completion, KeyIdentity
from gateway.providers import Provider, ProviderConfig
from gateway.settings import Settings


@dataclass
class Circuit:
    failures: int = 0
    opened: float = 0
    probing: bool = False
    healthy: bool = True


@dataclass
class RoutedCompletion:
    completion: Completion
    provider: str
    fallbacks: int
    latency: float
    cost: float
    charged_tokens: int


class Router:
    def __init__(
        self, configs: list[ProviderConfig], client: httpx.AsyncClient, settings: Settings
    ) -> None:
        self.settings = settings
        self.providers = [Provider(c, client, settings) for c in configs]
        self.states = {c.name: Circuit() for c in configs}
        self.observe_attempt: Callable[[str, float, bool], None] = lambda n, d, s: None

    def candidates(self, request: ChatRequest, key: KeyIdentity) -> list[Provider]:
        return sorted(
            [
                p
                for p in self.providers
                if request.model in p.config.models
                and p.config.estimate(request.prompt_reservation(), request.max_tokens)
                <= key.max_cost
            ],
            key=lambda p: (
                p.config.priority,
                p.config.estimate(request.prompt_reservation(), request.max_tokens),
            ),
        )

    def reservation_size(self, request: ChatRequest, key: KeyIdentity) -> int:
        return (
            (request.prompt_reservation() + request.max_tokens)
            * max(1, len(self.candidates(request, key)))
            * (self.settings.retries + 1)
        )

    async def check_health(self) -> None:
        results = await asyncio.gather(*(p.health() for p in self.providers))
        for provider, healthy in zip(self.providers, results, strict=True):
            self.states[provider.config.name].healthy = healthy

    def available(self) -> bool:
        return any(
            state.healthy
            and (
                state.failures < self.settings.circuit_threshold
                or time.monotonic() - state.opened >= self.settings.circuit_reset
            )
            for state in self.states.values()
        )

    async def complete(self, request: ChatRequest, key: KeyIdentity) -> RoutedCompletion:
        wasted = 0
        estimated_spent = 0.0
        fallback = 0
        last_provider: str | None = None
        for index, provider in enumerate(self.candidates(request, key)):
            config = provider.config
            state = self.states[config.name]
            if not state.healthy:
                continue
            if state.failures >= self.settings.circuit_threshold:
                if time.monotonic() - state.opened < self.settings.circuit_reset or state.probing:
                    continue
                state.probing = True
            started = time.monotonic()
            dispatched = False
            try:
                for attempt in range(self.settings.retries + 1):
                    upper_cost = config.estimate(request.prompt_reservation(), request.max_tokens)
                    if estimated_spent + upper_cost > key.max_cost:
                        break
                    if attempt == 0 and index > 0:
                        fallback += 1
                    last_provider = config.name
                    dispatched = True
                    try:
                        attempt_start = time.monotonic()
                        completion = await provider.complete(request)
                        self.observe_attempt(config.name, time.monotonic() - attempt_start, True)
                        state.failures = 0
                        return RoutedCompletion(
                            completion,
                            config.name,
                            fallback,
                            time.monotonic() - started,
                            estimated_spent
                            + config.estimate(
                                completion.prompt_tokens, completion.completion_tokens
                            ),
                            wasted + completion.total_tokens,
                        )
                    except GatewayError:
                        self.observe_attempt(config.name, time.monotonic() - attempt_start, False)
                        wasted += request.prompt_reservation() + request.max_tokens
                        estimated_spent += upper_cost
                        if attempt < self.settings.retries:
                            await asyncio.sleep(self.settings.backoff * 2**attempt)
                if dispatched:
                    state.failures += 1
                    state.opened = time.monotonic()
            finally:
                state.probing = False
        raise RoutingError(wasted, estimated_spent, fallback, last_provider)
