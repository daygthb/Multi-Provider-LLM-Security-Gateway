import base64
import binascii
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

Action = Literal["allow", "warn", "redact", "block"]
Direction = Literal["request", "response"]


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    direction: Direction
    pattern: str
    score: int = Field(ge=0, le=100)
    action: Action


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[Rule]


@dataclass
class Decision:
    text: str
    action: Action
    risk: int
    rules: list[str]


class PolicyEngine:
    def __init__(self, path: str) -> None:
        try:
            config = PolicyConfig.model_validate(yaml.safe_load(Path(path).read_text("utf-8")))
            self.rules = [
                (rule, re.compile(rule.pattern, re.IGNORECASE | re.MULTILINE))
                for rule in config.rules
            ]
        except (ValidationError, re.error, yaml.YAMLError) as exc:
            raise ValueError("Invalid security policy configuration") from exc

    def inspect(self, text: str, direction: Direction) -> Decision:
        # Inspect one bounded decoding layer. Redaction of transformed payloads cannot
        # safely map offsets to originals, so any decoded-only hit blocks instead.
        decoded = [unquote(text)] if "%" in text else []
        for candidate in re.findall(r"[A-Za-z0-9_+/-]{24,}={0,2}", text):
            try:
                decoded.append(
                    base64.b64decode(candidate, altchars=b"-_", validate=True).decode("utf-8")
                )
            except (ValueError, UnicodeDecodeError, binascii.Error):
                continue
        action: Action = "allow"
        rank = {"allow": 0, "warn": 1, "redact": 2, "block": 3}
        matches: list[str] = []
        risk = 0
        clean = text
        for rule, pattern in self.rules:
            if rule.direction != direction:
                continue
            direct = pattern.search(text) is not None
            indirect = any(pattern.search(value) for value in decoded)
            if not direct and not indirect:
                continue
            matches.append(rule.id)
            risk = min(100, risk + rule.score)
            chosen: Action = "block" if indirect else rule.action
            if rank[chosen] > rank[action]:
                action = chosen
            if rule.action == "redact" and direct:
                clean = pattern.sub(f"[REDACTED:{rule.id}]", clean)
        return Decision(clean, action, risk, matches)
