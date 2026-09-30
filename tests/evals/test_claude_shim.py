"""The OpenAI-compatible shim that serves competitor ingestion through ``claude -p``."""

from __future__ import annotations

import json
from typing import Any

from evals.claude_shim import render_prompt, to_message

TOOLS = [
    {
        "type": "function",
        "function": {"name": "read_file", "parameters": {"type": "object"}},
    }
]


def test_tool_request_turns_a_json_reply_into_tool_calls() -> None:
    body = {"messages": [{"role": "user", "content": "open index.md"}], "tools": TOOLS}
    assert "read_file" in render_prompt(body)
    message, finish = to_message(
        body,
        '```json\n{"tool_calls": [{"name": "read_file", "arguments": {"path": "index.md"}}]}\n```',
    )
    assert finish == "tool_calls"
    call = message["tool_calls"][0]["function"]
    assert call["name"] == "read_file" and json.loads(call["arguments"]) == {
        "path": "index.md"
    }


def test_tool_request_answered_without_a_tool_returns_content() -> None:
    body = {"messages": [{"role": "user", "content": "hi"}], "tools": TOOLS}
    message, finish = to_message(body, '{"content": "hello"}')
    assert (message["content"], finish) == ("hello", "stop")


def test_json_mode_extracts_the_object_from_surrounding_text() -> None:
    body = {
        "messages": [{"role": "user", "content": "facts"}],
        "response_format": {"type": "json_object"},
    }
    message, _ = to_message(body, 'Here you go: {"facts": ["a"]} done')
    assert json.loads(message["content"]) == {"facts": ["a"]}


def test_tool_results_and_prior_calls_reach_the_prompt() -> None:
    body = {
        "messages": [
            {"role": "system", "content": "be brief"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "# Index"},
        ]
    }
    prompt = render_prompt(body)
    assert (
        "be brief" in prompt and "[called read_file" in prompt and "# Index" in prompt
    )


def test_only_a_real_schema_constrains_the_reply() -> None:
    from evals.claude_shim import reply_schema

    given = {"type": "object", "properties": {"facts": {"type": "array"}}}
    assert (
        reply_schema(
            {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"schema": given},
                }
            }
        )
        == given
    )
    assert reply_schema({"response_format": {"type": "json_object"}}) is None
    assert reply_schema({"tools": TOOLS}) is None
    assert reply_schema({"messages": []}) is None


def test_cached_replies_count_their_original_usage(
    tmp_path: Any, monkeypatch: Any
) -> None:
    import evals.claude_shim as shim

    calls: list[Any] = []

    def fake(model: str, prompt: str, schema: Any = None) -> dict[str, Any]:
        calls.append(schema)
        return {
            "text": '{"facts": []}',
            "input_tokens": 100,
            "output_tokens": 10,
            "api_ms": 50,
        }

    monkeypatch.setattr(shim, "SHIM_CACHE", tmp_path)
    monkeypatch.setattr(shim, "SHIM_LOG", tmp_path / "log")
    monkeypatch.setattr(shim, "_claude", fake)
    schema = {"type": "object", "properties": {"facts": {"type": "array"}}}
    body = {
        "messages": [{"role": "user", "content": "x"}],
        "response_format": {"type": "json_schema", "json_schema": {"schema": schema}},
    }
    shim.complete(body, "build-a")
    shim.complete(body, "build-a")
    assert len(calls) == 1 and calls[0] == schema
    stats = shim.STATS["build-a"]
    assert (
        stats["calls"],
        stats["input_tokens"],
        stats["api_ms"],
        stats["unparseable"],
    ) == (2, 200, 100, 0)
