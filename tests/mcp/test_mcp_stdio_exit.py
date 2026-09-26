"""`ai mcp` over stdio exits once its client closes stdin."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_READY = "MCP server ready"


def test_stdio_server_exits_after_stdin_closes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("INQUIRY_")},
        "HOME": str(tmp_path / "home"),
        "INQUIRY_EMBEDDINGS_DEFAULT_PROVIDER": "hashing",
        "INQUIRY_EMBEDDINGS_DEFAULT_DIMENSIONS": "128",
    }
    log = tmp_path / "stderr.log"
    with log.open("wb") as stderr:
        server = subprocess.Popen(
            [sys.executable, "-m", "agentic_inquiry.cli", "mcp", "--project-id", "demo"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
            cwd=project,
            env=env,
        )
        try:
            deadline = time.monotonic() + 120
            while _READY not in log.read_text(errors="replace"):
                assert server.poll() is None, log.read_text(errors="replace")
                assert time.monotonic() < deadline, "server never became ready"
                time.sleep(0.2)

            assert server.stdin is not None
            server.stdin.close()
            returncode = server.wait(timeout=30)
        finally:
            if server.poll() is None:
                server.kill()
                server.wait()

    assert returncode == 0, log.read_text(errors="replace")
