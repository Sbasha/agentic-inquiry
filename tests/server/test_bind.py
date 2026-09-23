"""``bind_host`` is the only bind decision."""

from __future__ import annotations

import pytest

from agentic_inquiry.server.bind import bind_host


def test_bind_host_defaults_and_loopback() -> None:
    assert bind_host(None, auth_enabled=False) == "127.0.0.1"
    assert bind_host("localhost", False) == "localhost"
    assert bind_host("127.0.0.1", False) == "127.0.0.1"
    assert bind_host("::1", False) == "::1"


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "::ffff:0.0.0.0"])
def test_bind_host_refuses_non_loopback_without_auth(host: str) -> None:
    with pytest.raises(ValueError, match="API key"):
        bind_host(host, False)


def test_bind_host_refuses_an_unparseable_value() -> None:
    with pytest.raises(ValueError, match="not an address"):
        bind_host("not-an-address", False)


def test_bind_host_allows_non_loopback_when_auth_is_enabled() -> None:
    assert bind_host("0.0.0.0", True) == "0.0.0.0"
