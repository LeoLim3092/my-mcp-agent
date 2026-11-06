"""Provider formats use mocked HTTP; no model accounts or paid requests."""

import json
import unittest
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from my_mcp_agent.providers.base import Message, ProviderConfig
from my_mcp_agent.providers.http import HTTPModelAdapter


def config(protocol="chat_completions", **changes):
    return ProviderConfig(
        protocol=protocol,
        model="fake-model",
        endpoint="https://provider.invalid/chat",
        supports_tools=True,
        input_usd_per_million="0.1",
        output_usd_per_million="0.2",
        reservation_usd="0.01",
        **changes,
    )


def completion(content="done", calls=None):
    return {
        "choices": [
            {
                "message": {"content": content, "tool_calls": calls or []},
                "finish_reason": "tool_calls" if calls else "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_completion_format_and_usage(self):
        seen = []

        def respond(request):
            seen.append(json.loads(request.content))
            self.assertEqual(
                request.headers["Authorization"], "Bearer test-only-secret"
            )
            return httpx.Response(
                200,
                json=completion(
                    calls=[
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"rel_path":"GDD.md"}',
                            },
                        }
                    ]
                ),
            )

        adapter = HTTPModelAdapter(
            config(api_key_env="TEST_MODEL_KEY"), httpx.MockTransport(respond)
        )
        with patch.dict("os.environ", {"TEST_MODEL_KEY": "test-only-secret"}):
            prepared = adapter.prepare([Message(role="user", content="task")], [])
            reply = await adapter.send(prepared)
        self.assertFalse(seen[0]["stream"])
        self.assertEqual(seen[0]["max_completion_tokens"], 2048)
        self.assertEqual(reply.calls[0].name, "read_file")
        self.assertEqual(reply.usage.input_tokens, 100)
        self.assertNotIn("test-only-secret", json.dumps(prepared.payload))

    async def test_ollama_format_and_usage(self):
        def respond(request):
            data = json.loads(request.content)
            self.assertEqual(data["options"]["num_predict"], 2048)
            return httpx.Response(
                200,
                json={
                    "done": True,
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "workspace_ping", "arguments": {}}}
                        ],
                    },
                    "prompt_eval_count": 10,
                    "eval_count": 2,
                },
            )

        adapter = HTTPModelAdapter(config("ollama"), httpx.MockTransport(respond))
        reply = await adapter.send(
            adapter.prepare([Message(role="user", content="task")], [])
        )
        self.assertTrue(reply.calls[0].id)
        self.assertEqual(reply.usage.output_tokens, 2)

    async def test_missing_or_invalid_usage_is_not_invented(self):
        for usage in ({}, {"prompt_tokens": True, "completion_tokens": 1}):
            response = completion()
            response["usage"] = usage
            adapter = HTTPModelAdapter(
                config(),
                httpx.MockTransport(
                    lambda request, response=response: httpx.Response(
                        200, json=response
                    )
                ),
            )
            with self.assertRaises((KeyError, ValidationError)):
                await adapter.send(
                    adapter.prepare([Message(role="user", content="task")], [])
                )

    async def test_model_configuration_capability_endpoint_and_context_checks(self):
        base = config().model_dump()
        for change in (
            {"supports_tools": False},
            {"endpoint": "http://public.example/chat"},
            {"protocol": "unknown"},
            {"endpoint": "https://secret:password@example.com/chat"},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ProviderConfig.model_validate({**base, **change})
        adapter = HTTPModelAdapter(
            ProviderConfig.model_validate({**base, "reservation_usd": "0"})
        )
        with self.assertRaises(ValueError):
            adapter.prepare([Message(role="user", content="task")], [])
        adapter = HTTPModelAdapter(
            ProviderConfig.model_validate({**base, "max_input_bytes": 1000})
        )
        with self.assertRaises(ValueError):
            adapter.prepare([Message(role="user", content="x" * 2000)], [])

    async def test_timeout_and_oversized_responses_are_rejected(self):
        async def timeout(request):
            raise httpx.ReadTimeout("simulated")

        adapter = HTTPModelAdapter(config(), httpx.MockTransport(timeout))
        with self.assertRaises(httpx.ReadTimeout):
            await adapter.send(
                adapter.prepare([Message(role="user", content="task")], [])
            )
        adapter = HTTPModelAdapter(
            config(),
            httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"x" * 2_000_001)
            ),
        )
        with self.assertRaises(ValueError):
            await adapter.send(
                adapter.prepare([Message(role="user", content="task")], [])
            )
