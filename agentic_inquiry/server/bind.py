"""The one function that chooses a network bind address."""

from __future__ import annotations

import ipaddress
from typing import Any


def bind_host(requested: str | None, auth_enabled: bool) -> str:
    """Return the address a server may bind.

    Nothing requested means loopback. ``localhost`` is accepted as written.
    Any other value must parse as an IP address and be loopback, unless API-key
    authentication is enabled with a configured key.
    """
    if requested is None or requested == "":
        return "127.0.0.1"
    if requested == "localhost":
        return requested
    try:
        address = ipaddress.ip_address(requested)
    except ValueError as exc:
        raise ValueError(f"{requested!r} is not an address") from exc
    if address.is_loopback or auth_enabled:
        return requested
    raise ValueError("a non-loopback bind requires an API key")


def rest_auth_enabled(config: Any) -> bool:
    """True when the REST API key is enabled and a key is configured."""
    api = getattr(getattr(config, "mcp", None), "api", None)
    auth = getattr(api, "auth", None)
    if isinstance(auth, dict):
        enabled = bool(auth.get("enabled"))
        key = auth.get("api_key")
    else:
        enabled = bool(getattr(auth, "enabled", False))
        key = getattr(auth, "api_key", None)
    return enabled and isinstance(key, str) and bool(key.strip())
