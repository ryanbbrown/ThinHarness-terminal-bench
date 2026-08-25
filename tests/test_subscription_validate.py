from __future__ import annotations

import pytest

from tbench.budget import api_equivalent_cost_usd
from tbench.subscription_validate import SubscriptionValidationError, _request_batching, _usage_from_audits


def test_gateway_usage_requires_exact_cache_write_and_prices_frozen_schedule() -> None:
    audits = [
        {
            "usage": {
                "input_tokens": 150,
                "input_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 20},
                "output_tokens": 10,
                "output_tokens_details": {"reasoning_tokens": 4},
            },
            "response": {"output": []},
        }
    ]

    usage = _usage_from_audits(audits)

    assert usage == {
        "input_tokens": 150,
        "ordinary_input_tokens": 30,
        "cached_input_tokens": 100,
        "cache_write_tokens": 20,
        "output_tokens": 10,
        "reasoning_tokens": 4,
        "api_equivalent_cost_usd": api_equivalent_cost_usd(
            ordinary_input_tokens=30,
            cached_input_tokens=100,
            cache_write_tokens=20,
            output_tokens=10,
        ),
    }


def test_gateway_usage_fails_closed_when_cache_write_is_missing() -> None:
    audits = [
        {
            "usage": {
                "input_tokens": 1,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens": 1,
                "output_tokens_details": {"reasoning_tokens": 0},
            }
        }
    ]
    with pytest.raises(SubscriptionValidationError, match="cache-write"):
        _usage_from_audits(audits)


def test_request_batching_preserves_calls_per_response() -> None:
    audits = [
        {"response": {"output": [{"type": "function_call"}, {"type": "message"}, {"type": "function_call"}]}},
        {"response": {"output": [{"type": "message"}]}},
    ]
    assert _request_batching(audits) == {
        "tool_calls_per_response": [2, 0],
        "tool_bearing_responses": 1,
        "multi_tool_responses": 1,
        "max_tool_calls_in_response": 2,
    }
