"""Nonstreaming Chat Completions-compatible and native Ollama adapters."""

import asyncio
import json
import os
from decimal import Decimal
from uuid import uuid4

import httpx

from my_mcp_agent.providers.base import (
    Message,
    ModelReply,
    PreparedRequest,
    ProviderConfig,
    ToolCall,
    Usage,
)


class HTTPModelAdapter:
    """Trusted endpoint/rates; no automatic retries, redirects or proxy credentials."""

    def __init__(self, config: ProviderConfig, transport=None):
        if config.protocol not in {"chat_completions", "ollama"}:
            raise ValueError("Unsupported HTTP provider protocol.")
        self.config = config
        self._transport = transport

    def prepare(self, messages: list[Message], tools: list[dict]) -> PreparedRequest:
        if self.config.api_key_env and (not os.environ.get(self.config.api_key_env)):
            raise ValueError(
                "Configured provider API-key environment variable is missing."
            )
        history = []
        for message in messages:
            item = {"role": message.role, "content": message.content}
            if message.calls:
                item["tool_calls"] = []
                for call in message.calls:
                    function = {"name": call.name, "arguments": call.arguments}
                    if self.config.protocol == "chat_completions":
                        function["arguments"] = (
                            json.dumps(call.arguments)
                            if isinstance(call.arguments, dict)
                            else call.arguments
                        )
                        item["tool_calls"].append(
                            {"id": call.id, "type": "function", "function": function}
                        )
                    else:
                        if isinstance(function["arguments"], str):
                            try:
                                function["arguments"] = json.loads(
                                    function["arguments"]
                                )
                            except ValueError:
                                function["arguments"] = {}
                        item["tool_calls"].append({"function": function})
            if message.role == "tool":
                if self.config.protocol == "chat_completions":
                    item["tool_call_id"] = message.call_id
                else:
                    item["tool_name"] = message.name
            history.append(item)
        payload = {
            "model": self.config.model,
            "messages": history,
            "stream": False,
            "tools": [{"type": "function", "function": tool} for tool in tools],
        }
        if self.config.protocol == "chat_completions":
            payload[self.config.completion_token_parameter] = (
                self.config.max_output_tokens
            )
        else:
            payload["options"] = {"num_predict": self.config.max_output_tokens}
        if (
            len(json.dumps(payload, ensure_ascii=False).encode())
            > self.config.max_input_bytes
        ):
            raise ValueError(
                "Provider request exceeds the configured context byte limit."
            )
        estimate = self.config.cost(
            Usage(
                input_tokens=len(json.dumps(payload, ensure_ascii=False).encode()),
                output_tokens=self.config.max_output_tokens,
            )
        )
        if Decimal(self.config.reservation_usd) < Decimal(estimate):
            raise ValueError(
                "Reservation is below the request's conservative token-cost allowance."
            )
        return PreparedRequest(payload=payload)

    async def send(self, request: PreparedRequest) -> ModelReply:
        headers = {"Accept-Encoding": "identity"}
        if self.config.api_key_env:
            headers["Authorization"] = "Bearer " + os.environ[self.config.api_key_env]
        async with (
            asyncio.timeout(self.config.timeout_seconds),
            httpx.AsyncClient(
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=self.config.timeout_seconds,
            ) as client,
            client.stream(
                "POST", self.config.endpoint, json=request.payload, headers=headers
            ) as response,
        ):
            response.raise_for_status()
            if (
                response.headers.get("content-encoding", "identity").lower()
                != "identity"
            ):
                raise ValueError("Compressed provider responses are not supported.")
            raw = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=16384):
                raw.extend(chunk)
                if len(raw) > 2000000:
                    raise ValueError("Provider response exceeds 2 MB.")
        data = json.loads(raw)
        calls = []
        if self.config.protocol == "chat_completions":
            usage = Usage(
                input_tokens=data["usage"]["prompt_tokens"],
                output_tokens=data["usage"]["completion_tokens"],
            )
            if len(data["choices"]) != 1:
                raise ValueError("Exactly one provider completion is required.")
            choice = data["choices"][0]
            if choice["finish_reason"] not in {"stop", "tool_calls"}:
                raise ValueError(
                    "Truncated/refused provider reply requires operator review."
                )
            message = choice["message"]
            for call in message.get("tool_calls") or []:
                if call.get("type") != "function":
                    raise ValueError("Only function tool calls are supported.")
                calls.append(
                    ToolCall(
                        id=call["id"],
                        name=call["function"]["name"],
                        arguments=call["function"]["arguments"],
                    )
                )
        else:
            if data.get("done") is not True or data.get("done_reason", "stop") not in {
                "stop",
                "tool_calls",
            }:
                raise ValueError("Incomplete provider reply requires operator review.")
            usage = Usage(
                input_tokens=data["prompt_eval_count"], output_tokens=data["eval_count"]
            )
            message = data["message"]
            for call in message.get("tool_calls") or []:
                calls.append(
                    ToolCall(
                        id=call.get("id") or f"call_{uuid4().hex}",
                        name=call["function"]["name"],
                        arguments=call["function"]["arguments"],
                    )
                )
        return ModelReply(
            text=message.get("content") or "", calls=tuple(calls), usage=usage
        )
