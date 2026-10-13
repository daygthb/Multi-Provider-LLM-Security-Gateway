import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from gateway.models import ChatRequest


class MockRequest(ChatRequest):
    stream_options: dict[str, bool] | None = None


app = FastAPI(title="Deterministic mock LLM provider")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": "mock-model", "object": "model"}]}


@app.post("/v1/chat/completions", response_model=None)
async def chat(request: MockRequest) -> dict[str, Any] | StreamingResponse:
    # Echo makes redaction visibly testable; no paid credentials or random generation.
    text = "Mock response: " + request.messages[-1].content
    text = text[: request.max_tokens]
    prompt = max(1, sum(len(m.content) for m in request.messages) // 4)
    output = max(1, len(text) // 4)
    usage = {"prompt_tokens": prompt, "completion_tokens": output, "total_tokens": prompt + output}
    base = {"id": "chatcmpl-mock", "created": int(time.time()), "model": request.model}
    if not request.stream:
        return {
            **base,
            "object": "chat.completion",
            "usage": usage,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
        }

    async def events() -> AsyncIterator[str]:
        for i in range(0, len(text), 8):
            event = {
                **base,
                "object": "chat.completion.chunk",
                "choices": [
                    {"index": 0, "delta": {"content": text[i : i + 8]}, "finish_reason": None}
                ],
            }
            yield "data: " + json.dumps(event) + "\n\n"
        yield (
            "data: "
            + json.dumps(
                {
                    **base,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": usage,
                }
            )
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
