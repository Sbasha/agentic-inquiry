"""The container entrypoint refuses a non-loopback host without an API key."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_wildcard_host_without_an_api_key_exits() -> None:
    env = {k: v for k, v in os.environ.items() if k != "INQUIRY_MCP_API_AUTH_API_KEY"}
    env["INQUIRY_SERVER_HOST"] = "0.0.0.0"
    completed = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "entrypoint.py")],
        capture_output=True,
        env=env,
        timeout=30,
        cwd=REPO,
    )
    text = completed.stderr.decode("utf-8")
    assert completed.returncode == 1
    assert "INQUIRY_SERVER_HOST" in text
    assert "INQUIRY_MCP_API_AUTH_API_KEY" in text
    assert "Traceback" not in text
