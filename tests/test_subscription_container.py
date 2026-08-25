from __future__ import annotations

import asyncio
import inspect

import httpx

from tbench import subscription_container
from tbench.subscription_container import _parse_pi_events, _provider_transport_identity, _subscription_provider


def test_pi_event_parser_preserves_request_tool_and_reasoning_usage() -> None:
    events = [
        {"type": "tool_execution_start", "toolName": "bash", "args": {"command": "true"}},
        {"type": "tool_execution_end", "toolName": "bash", "isError": False},
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "model": "gpt-5.6-sol",
                "stopReason": "toolUse",
                "usage": {"input": 3, "cacheRead": 4, "cacheWrite": 5, "output": 6, "reasoning": 2},
            },
        },
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "model": "gpt-5.6-sol",
                "stopReason": "stop",
                "usage": {"input": 7, "cacheRead": 8, "cacheWrite": 9, "output": 10, "reasoning": 4},
            },
        },
    ]
    value = _parse_pi_events(events)
    assert value["request_count"] == 2
    assert value["tool_count"] == 1
    assert value["tool_call_names"] == ["bash"]
    assert value["usage"] == {
        "ordinary_input_tokens": 10,
        "cached_input_tokens": 12,
        "cache_write_tokens": 14,
        "output_tokens": 16,
        "reasoning_tokens": 6,
        "input_tokens": 36,
    }
    assert value["response_models"] == ["gpt-5.6-sol"]
    assert value["stop_reason"] == "stop"


def test_pi_instruction_uses_end_of_options_boundary() -> None:
    source = inspect.getsource(subscription_container._run_pi)
    assert '"--",\n        instruction,' in source


def test_native_provider_owns_client_with_effective_1800_second_timeout() -> None:
    class ControlledNativeProvider:
        def __init__(self, **kwargs: object) -> None:
            assert "http_client" not in kwargs
            assert isinstance(kwargs["timeout"], int)
            self.timeout = kwargs["timeout"]
            self._http_client: httpx.AsyncClient | None = None
            self._owns_client = True

        def _client(self) -> httpx.AsyncClient:
            if self._http_client is None:
                self._http_client = httpx.AsyncClient(timeout=self.timeout)
            return self._http_client

        async def create_response(self, payload: dict[str, object]) -> dict[str, object]:
            return payload

    provider = _subscription_provider(
        ControlledNativeProvider, RuntimeError, url="http://127.0.0.1:1/v1", token="controlled", requests=[]
    )
    identity = _provider_transport_identity(provider)

    assert identity == {
        "provider_timeout_seconds": 1800,
        "client_timeout_seconds": {"connect": 1800, "read": 1800, "write": 1800, "pool": 1800},
        "provider_owns_client": True,
        "client_type": "httpx.AsyncClient",
        "requests_made": 0,
    }
    assert "http_client=" not in inspect.getsource(subscription_container._subscription_provider)
    assert provider._http_client is not None
    asyncio.run(provider._http_client.aclose())
