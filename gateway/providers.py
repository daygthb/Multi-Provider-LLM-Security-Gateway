import json
import os
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from gateway.errors import GatewayError
from gateway.models import ChatRequest, Completion
from gateway.settings import Settings


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z0-9_-]+$")
    kind: Literal["openai", "ollama", "mock"]
    base_url: str
    api_key_env: str | None = None
    models: dict[str, str] = Field(min_length=1)
    priority: int = Field(default=0, ge=0)
    input_cost_per_million: float = Field(default=0, ge=0)
    output_cost_per_million: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_url(self) -> "ProviderConfig":
        url = httpx.URL(self.base_url)
        if url.scheme not in {"http", "https"} or not url.host or url.userinfo or url.query:
            raise ValueError("provider URL must be HTTP(S) without credentials or query")
        return self

    def estimate(self, prompt: int, output: int) -> float:
        return (prompt * self.input_cost_per_million + output * self.output_cost_per_million) / 1e6


class ProviderFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    providers: list[ProviderConfig] = Field(min_length=1, max_length=16)


def load_providers(path: str) -> list[ProviderConfig]:
    configs = ProviderFile.model_validate(yaml.safe_load(Path(path).read_text("utf-8"))).providers
    if len({p.name for p in configs}) != len(configs):
        raise ValueError("provider names must be unique")
    return configs


class Provider:
    def __init__(
        self, config: ProviderConfig, client: httpx.AsyncClient, settings: Settings
    ) -> None:
        self.config, self.client, self.settings = config, client, settings

    def headers(self) -> dict[str, str]:
        headers = {"Accept-Encoding": "identity"}
        if self.config.api_key_env:
            value = os.environ.get(self.config.api_key_env)
            if not value:
                raise GatewayError(503, "provider_unavailable", "Provider credentials unavailable")
            headers["Authorization"] = f"Bearer {value}"
        return headers

    async def health(self) -> bool:
        path = "/api/tags" if self.config.kind == "ollama" else "/v1/models"
        try:
            async with self.client.stream(
                "GET",
                self.config.base_url.rstrip("/") + path,
                headers=self.headers(),
                timeout=self.settings.upstream_timeout,
            ) as response:
                return response.is_success
        except (httpx.HTTPError, GatewayError):
            return False

    async def complete(self, request: ChatRequest) -> Completion:
        body: dict[str, Any] = request.model_dump(exclude_none=True)
        body["model"] = self.config.models[request.model]
        path = "/v1/chat/completions"
        if self.config.kind == "ollama":
            path = "/api/chat"
            body = {
                "model": body["model"],
                "messages": body["messages"],
                "stream": request.stream,
                "options": {"num_predict": request.max_tokens, "temperature": request.temperature},
            }
        elif request.stream:
            body["stream_options"] = {"include_usage": True}
        try:
            async with self.client.stream(
                "POST",
                self.config.base_url.rstrip("/") + path,
                json=body,
                headers=self.headers(),
                timeout=self.settings.upstream_timeout,
            ) as response:
                if not response.is_success:
                    raise GatewayError(502, "provider_error", "Upstream provider rejected request")
                if (
                    response.headers.get("content-encoding", "identity").strip().lower()
                    != "identity"
                ):
                    raise GatewayError(
                        502, "provider_error", "Unsupported upstream content encoding"
                    )
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(data) + len(chunk) > self.settings.max_response_bytes:
                        raise GatewayError(
                            502, "provider_error", "Upstream response exceeded limit"
                        )
                    data.extend(chunk)
            value = data.decode("utf-8")
            result = (
                self.parse_stream(value, request)
                if request.stream
                else self.parse_json(json.loads(value), request)
            )
            if (
                result.completion_tokens > request.max_tokens
                or result.prompt_tokens > request.prompt_reservation()
            ):
                raise ValueError("usage exceeds reservation")
            return result
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            RecursionError,
        ) as exc:
            raise GatewayError(
                502, "provider_error", "Invalid or unavailable upstream response"
            ) from exc

    def parse_json(self, value: Any, request: ChatRequest) -> Completion:
        if self.config.kind == "ollama":
            text = value["message"]["content"]
            prompt, output = value.get("prompt_eval_count"), value.get("eval_count")
            finish = value.get("done_reason", "stop")
        else:
            choice = value["choices"][0]
            text, finish = choice["message"]["content"], choice.get("finish_reason", "stop")
            usage = value.get("usage") or {}
            prompt, output = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if not isinstance(text, str):
            raise ValueError("unsupported upstream content")
        # Missing usage charges the full admitted reservation, never a guessed discount.
        return Completion(
            text=text,
            prompt_tokens=prompt if prompt is not None else request.prompt_reservation(),
            completion_tokens=output if output is not None else request.max_tokens,
            finish_reason=finish,
        )

    def parse_stream(self, text: str, request: ChatRequest) -> Completion:
        parts: list[str] = []
        prompt: int | None = None
        output: int | None = None
        finish = "stop"
        done = False
        for line in text.splitlines():
            if not line.strip() or line.startswith(":"):
                continue
            if self.config.kind != "ollama":
                if not line.startswith("data:"):
                    continue
                line = line[5:].strip()
                if line == "[DONE]":
                    done = True
                    continue
            event = json.loads(line)
            if self.config.kind == "ollama":
                parts.append(event.get("message", {}).get("content", ""))
                if event.get("done"):
                    done = True
                    prompt, output = event.get("prompt_eval_count"), event.get("eval_count")
                    finish = event.get("done_reason", "stop")
            else:
                for choice in event["choices"]:
                    parts.append(choice.get("delta", {}).get("content", ""))
                    finish = choice.get("finish_reason") or finish
                if event.get("usage"):
                    prompt = event["usage"].get("prompt_tokens")
                    output = event["usage"].get("completion_tokens")
        if not done:
            raise ValueError("truncated upstream stream")
        # Reuse schema validation and conservative missing-usage accounting.
        payload: dict[str, Any]
        if self.config.kind == "ollama":
            payload = {
                "message": {"content": "".join(parts)},
                "prompt_eval_count": prompt,
                "eval_count": output,
                "done_reason": finish,
            }
        else:
            payload = {
                "choices": [{"message": {"content": "".join(parts)}, "finish_reason": finish}],
                "usage": {"prompt_tokens": prompt, "completion_tokens": output},
            }
        return self.parse_json(payload, request)
