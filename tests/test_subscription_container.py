from __future__ import annotations

from tbench.subscription_container import _parse_pi_events


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
