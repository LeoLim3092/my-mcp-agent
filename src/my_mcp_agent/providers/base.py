"""Normalized provider messages, usage, configuration and adapter interface."""

import hashlib
import json
from decimal import ROUND_CEILING, Decimal
from typing import Annotated, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from my_mcp_agent.contracts import CostUSD, Identity, TokenCount


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: Literal["chat_completions", "ollama", "demo"]
    model: Identity
    endpoint: str = ""
    api_key_env: Annotated[str | None, Field(pattern=r"^[A-Z_][A-Z0-9_]*$")] = None
    supports_tools: Annotated[bool, Field(strict=True)] = False
    input_usd_per_million: CostUSD
    output_usd_per_million: CostUSD
    reservation_usd: CostUSD
    completion_token_parameter: Literal["max_completion_tokens", "max_tokens"] = (
        "max_completion_tokens"
    )
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=65_536)] = 2048
    max_input_bytes: Annotated[int, Field(strict=True, ge=1000, le=1_000_000)] = 128_000
    timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 60

    @model_validator(mode="after")
    def check_endpoint(self):
        for amount in (
            self.input_usd_per_million,
            self.output_usd_per_million,
            self.reservation_usd,
        ):
            if Decimal(amount) > Decimal(1_000_000_000):
                raise ValueError(
                    "Configured monetary values must not exceed 1 billion USD."
                )
        if not self.supports_tools:
            raise ValueError("A tool-capable model must be explicitly configured.")
        if self.protocol != "demo":
            url = urlsplit(self.endpoint)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.fragment
                or url.query
            ):
                raise ValueError(
                    "Configure an HTTP(S) endpoint without credentials, query, or fragment."
                )
            if url.port is not None and not 1 <= url.port <= 65535:
                raise ValueError("Invalid provider endpoint port.")
            if url.scheme == "http" and url.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError(
                    "Remote providers require HTTPS; HTTP is limited to loopback."
                )
        return self

    def cost(self, usage: Usage) -> str:
        amount = (
            Decimal(usage.input_tokens) * Decimal(self.input_usd_per_million)
            + Decimal(usage.output_tokens) * Decimal(self.output_usd_per_million)
        ) / Decimal(1_000_000)
        return format(
            amount.quantize(Decimal("0.000000000001"), rounding=ROUND_CEILING), "f"
        )


class Usage(BaseModel):
    input_tokens: TokenCount
    output_tokens: TokenCount


class ToolCall(BaseModel):
    id: Annotated[str, Field(min_length=1, max_length=128)]
    name: Annotated[str, Field(min_length=1, max_length=128)]
    arguments: dict | str


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    calls: tuple[ToolCall, ...] = ()
    call_id: str | None = None
    name: str | None = None


class ModelReply(BaseModel):
    text: str = ""
    calls: Annotated[tuple[ToolCall, ...], Field(max_length=16)] = ()
    usage: Usage


class PreparedRequest(BaseModel):
    payload: dict

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.payload, sort_keys=True).encode()
        ).hexdigest()


class ModelAdapter(Protocol):
    config: ProviderConfig

    def prepare(
        self, messages: list[Message], tools: list[dict]
    ) -> PreparedRequest: ...
    async def send(self, request: PreparedRequest) -> ModelReply: ...


class ReviewDecision(BaseModel):
    approved: bool
    feedback: str = ""

    @model_validator(mode="after")
    def requires_feedback(self):
        if not self.approved and not self.feedback.strip():
            raise ValueError("A revision decision requires feedback.")
        return self
