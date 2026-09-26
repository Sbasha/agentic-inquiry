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
_MODEL_CACHE = "models--sentence-transformers--all-MiniLM-L6-v2"


def test_stdio_server_exits_after_stdin_closes(tmp_path: Path) -> None:
    # ai mcp loads the sentence-transformer whatever the configured provider;
    # use the developer's cache offline rather than download it per run.
    from huggingface_hub import constants

    hub_cache = Path(constants.HF_HUB_CACHE)
    if not (hub_cache / _MODEL_CACHE).is_dir():
        pytest.skip(f"{_MODEL_CACHE} is not in the HuggingFace cache")
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("INQUIRY_")},
        "HOME": str(tmp_path / "home"),
        "HF_HUB_CACHE": str(hub_cache),
        "HF_HUB_OFFLINE": "1",
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
