"""Base deploy command infrastructure."""

from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agv.deploy")

DEPLOY_DIR = ".agv/deploy"


@dataclass
class DeployStep:
    """A single step in a deploy script."""
    name: str
    description: str
    completed: bool = False
    output: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class DeployState:
    """Resume file tracking deploy progress."""
    provider: str
    started_at: str
    steps: list[DeployStep] = field(default_factory=list)
    api_key: str = ""
    server_url: str | None = None

    def save(self, path: Path) -> None:
        """Write resume state to JSON."""
        import dataclasses
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(dataclasses.asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> Optional["DeployState"]:
        """Load resume state from JSON, or None if not found."""
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        steps = [DeployStep(**s) for s in data.pop("steps", [])]
        return cls(**data, steps=steps)


def generate_api_key() -> str:
    """Generate a 32-byte hex API key."""
    return secrets.token_hex(32)


def run_shell_script(
    script_path: str,
    env: dict[str, str] | None = None,
    timeout: int = 1200,
) -> subprocess.CompletedProcess:
    """Run a cloud-specific shell script with environment."""
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", script_path],
        env=merged_env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def smoke_test(server_url: str, timeout: int = 300) -> bool:
    """Poll health endpoint until it returns 200 or timeout."""
    import urllib.request
    import urllib.error

    deadline = time.time() + timeout
    health_url = f"{server_url.rstrip('/')}/api/v1/health"
    while time.time() < deadline:
        try:
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(5)
    return False
