"""``ai capabilities`` — what this runtime actually supports."""

from __future__ import annotations

import json
import sys
from typing import Any

from agentic_inquiry.integration.contract import (
    CLIENTS,
    EVENTS,
    HOOK_SCHEMA_VERSION,
    MAX_HOOK_INPUT_BYTES,
    PRODUCT,
    RUNTIME_CAPABILITIES,
    SCHEMA_VERSION,
    UNSUPPORTED_EVENTS,
    product_version,
)


def capabilities() -> dict[str, Any]:
    """The capability report. The client table is derived from the contract constants."""
    clients = {
        client: {
            "supported_events": list(EVENTS),
            "unsupported_events": list(UNSUPPORTED_EVENTS),
            "activation": "explicit per-project and client owner",
            "native_observed": False,
        }
        for client in CLIENTS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "product": PRODUCT,
        "version": product_version(),
        "contract_versions": {"cli": 1, "mcp": 1, "hook": 1},
        "hook_schema_version": HOOK_SCHEMA_VERSION,
        "runtime": dict(RUNTIME_CAPABILITIES),
        "clients": clients,
        "generative_model_calls": False,
        "capture_default": "inert",
        "max_hook_input_bytes": MAX_HOOK_INPUT_BYTES,
    }


def main(argv: list[str] | None = None) -> int:
    """Print the report. ``--json`` is accepted and is the default."""
    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg not in {"--json"} for arg in args):
        print("Unknown arguments for capabilities", file=sys.stderr)
        return 1
    json.dump(capabilities(), sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0
