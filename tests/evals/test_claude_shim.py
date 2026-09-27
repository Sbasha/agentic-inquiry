"""The OpenAI-compatible shim that serves competitor ingestion through ``claude -p``."""

from __future__ import annotations

import json

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
