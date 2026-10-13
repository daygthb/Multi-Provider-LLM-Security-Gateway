from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "developer", "user", "assistant"]
    content: str = Field(max_length=32000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=128, pattern=r"^[\w./:-]+$")
    messages: list[Message] = Field(min_length=1, max_length=64)
    stream: bool = False
    max_tokens: int = Field(default=256, ge=1, le=8192)
    temperature: float = Field(default=0.7, ge=0, le=2)
    n: Literal[1] = 1

    def prompt_reservation(self) -> int:
        # UTF-8 bytes + framing deliberately overestimate common byte/BPE tokenizers.
        return sum(len(m.content.encode("utf-8")) + 16 for m in self.messages) + 16


class KeyIdentity(BaseModel):
    id: str
    tenant: str
    allowed_models: list[str]
    permissions: list[str]
    rpm: int = Field(gt=0)
    tpm: int = Field(gt=0)
    monthly_budget: int = Field(gt=0)
    max_cost: float = Field(default=1, ge=0)


class Completion(BaseModel):
    text: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    finish_reason: Literal["stop", "length"] = "stop"

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens
