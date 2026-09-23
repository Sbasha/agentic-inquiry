"""MCP http and sse refuse a non-loopback host before any socket opens."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agentic_inquiry.mcp.server import MCPServer


def _config(host: str) -> SimpleNamespace:
    return SimpleNamespace(
        mcp=SimpleNamespace(
            enabled=True,
            api=SimpleNamespace(
                host=host, port=8765, auth={"enabled": True, "api_key": "secret"}
            ),
        )
    )


@pytest.mark.parametrize("runner", ["run", "run_async"])
def test_unspecified_host_refuses_a_wildcard_config(
    monkeypatch: pytest.MonkeyPatch, runner: str
) -> None:
    monkeypatch.setattr("fastmcp.FastMCP.run", lambda *args, **kwargs: None)
    monkeypatch.setattr("fastmcp.FastMCP.run_async", lambda *args, **kwargs: None)
    server = MCPServer(config=_config("0.0.0.0"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="reverse proxy") as caught:
        if runner == "run":
            server.run(transport="http", host=None)
        else:
            asyncio.run(server.run_async(transport="http", host=None))
    assert "API key" not in str(caught.value)
