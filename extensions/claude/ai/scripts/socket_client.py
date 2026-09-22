#!/usr/bin/env python3
"""Shared daemon communication helper for ai hook scripts.

All hook scripts use this to communicate with the ai daemon over Unix socket.
Handles connection, request/response, timeouts, and graceful fallback.
"""

import hashlib
import json
import os
import socket
import sys
from pathlib import Path


def get_socket_path(workspace: str | None = None) -> str:
    """Get the daemon socket path for a workspace.

    Uses workspace-hashed path for project isolation.
    """
    socket_dir = os.environ.get("AI_HOME", os.path.expanduser("~/.agentic-inquiry"))
    if workspace:
        project_hash = hashlib.sha256(
            os.path.abspath(workspace).encode()
        ).hexdigest()[:16]
        return os.path.join(socket_dir, f"daemon-{project_hash}.sock")
    return os.path.join(socket_dir, "daemon.sock")


def daemon_request(
    endpoint: str,
    data: dict | None = None,
    timeout: float = 2.0,
    workspace: str | None = None,
) -> dict | None:
    """Send a request to the daemon and return the response.

    Returns None on connection failure (daemon not running).
    """
    sock_path = get_socket_path(workspace)

    if not os.path.exists(sock_path):
        return None

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(sock_path)

        # Build HTTP request
        body = json.dumps(data or {}).encode()
        method = "POST" if data is not None else "GET"
        request = (
            f"{method} {endpoint} HTTP/1.1\r\n"
            f"Host: localhost\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"\r\n"
        ).encode() + body

        sock.sendall(request)

        # Read response
        response = b""
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                # Check if we've received the full response
                if b"\r\n\r\n" in response:
                    header_end = response.index(b"\r\n\r\n") + 4
                    headers = response[:header_end].decode()
                    # Parse Content-Length
                    content_length = 0
                    for line in headers.split("\r\n"):
                        if line.lower().startswith("content-length:"):
                            content_length = int(line.split(":")[1].strip())
                            break
                    body_received = len(response) - header_end
                    if body_received >= content_length:
                        break
            except socket.timeout:
                break

        sock.close()

        # Parse response body
        if b"\r\n\r\n" in response:
            body_start = response.index(b"\r\n\r\n") + 4
            body_bytes = response[body_start:]
            if body_bytes:
                return json.loads(body_bytes)
        return {}

    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return None
    except (json.JSONDecodeError, ValueError):
        return {}


def daemon_fire_and_forget(
    endpoint: str,
    data: dict,
    workspace: str | None = None,
) -> bool:
    """Send a request to the daemon without waiting for response.

    Returns True if the request was sent successfully.
    """
    sock_path = get_socket_path(workspace)

    if not os.path.exists(sock_path):
        return False

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(sock_path)

        body = json.dumps(data).encode()
        request = (
            f"POST {endpoint} HTTP/1.1\r\n"
            f"Host: localhost\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode() + body

        sock.sendall(request)
        sock.close()
        return True
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return False


def read_hook_input() -> dict:
    """Read and parse JSON input from stdin (Claude Code hook protocol)."""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    except (json.JSONDecodeError, ValueError, IOError):
        pass
    return {}


def hook_output(
    continue_: bool = True,
    system_message: str | None = None,
    hook_specific: dict | None = None,
) -> None:
    """Write JSON output for Claude Code hook protocol."""
    result: dict = {"continue": continue_}
    if system_message:
        result["systemMessage"] = system_message
    if hook_specific:
        result["hookSpecificOutput"] = hook_specific
    print(json.dumps(result))


def get_workspace() -> str:
    """Get the current workspace path from environment or cwd."""
    return os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())


def get_session_id() -> str:
    """Get the current session ID from environment."""
    return os.environ.get("CLAUDE_SESSION_ID", "unknown")


def start_daemon_if_needed(workspace: str) -> bool:
    """Start the daemon if it's not already running.

    Returns True if daemon is (now) running.
    """
    sock_path = get_socket_path(workspace)
    if os.path.exists(sock_path):
        # Check if daemon is responsive
        result = daemon_request("/health", workspace=workspace, timeout=1.0)
        if result is not None:
            return True

    # Try to start the daemon
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        # Fallback for dev mode (no CLAUDE_PLUGIN_ROOT set)
        plugin_root = str(Path(__file__).parent.parent)
    daemon_main = str(Path(plugin_root) / "servers" / "daemon" / "__main__.py")

    try:
        import subprocess

        subprocess.Popen(
            [
                sys.executable,
                daemon_main,
                "--workspace",
                workspace,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Wait for daemon to be ready (up to 3s)
        import time

        for _ in range(30):
            time.sleep(0.1)
            if os.path.exists(sock_path):
                result = daemon_request(
                    "/health", workspace=workspace, timeout=0.5
                )
                if result is not None:
                    return True
        return False
    except Exception:
        return False
