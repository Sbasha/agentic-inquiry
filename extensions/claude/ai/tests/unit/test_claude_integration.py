"""The plugin gives Claude Code a native search tool and points Grep users at it."""

from __future__ import annotations

import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]


def test_plugin_registers_the_search_tool() -> None:
    server = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]["inquiry"]
    assert server["command"] == "ai"
    assert server["args"] == ["mcp", "--tools", "search"]


def test_grep_hook_suggests_the_search_tool() -> None:
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    grep = next(
        h for h in hooks.get("hooks", hooks)["PreToolUse"] if h["matcher"] == "Grep"
    )
    prompt = grep["hooks"][0]["prompt"]
    assert "mcp__inquiry__search" in prompt and "/ai:search" not in prompt
