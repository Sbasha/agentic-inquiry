"""Server lifecycle management - PID file, auto-start, port discovery.

Supports multiple server instances via environment names. Each env
gets its own PID file, lock file, and default port:
  - "default" → server.pid, port 8765 (production/main)
  - "test"    → server-test.pid, port 8766 (ai-dev testing)
"""

import fcntl
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("ai.server.lifecycle")

# Defaults
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
TEST_PORT = 8766
MAX_PORT_RETRIES = 3
HEALTH_CHECK_TIMEOUT = 5.0
HEALTH_CHECK_INTERVAL = 0.2

# Environment name for test instances
ENV_DEFAULT = "default"
ENV_TEST = "test"


def _default_port_for_env(env: str) -> int:
    """Get the default port for an environment."""
    if env == ENV_TEST:
        return TEST_PORT
    return DEFAULT_PORT


def get_agv_home() -> str:
    """Get the ai home directory."""
    return os.environ.get("AI_HOME", os.path.expanduser("~/.agentic-inquiry"))


def get_pid_path(env: str = ENV_DEFAULT) -> str:
    """Get the server PID file path for an environment."""
    if env == ENV_DEFAULT:
        return os.path.join(get_agv_home(), "server.pid")
    return os.path.join(get_agv_home(), f"server-{env}.pid")


def get_lock_path(env: str = ENV_DEFAULT) -> str:
    """Get the server lock file path for an environment."""
    if env == ENV_DEFAULT:
        return os.path.join(get_agv_home(), "server.lock")
    return os.path.join(get_agv_home(), f"server-{env}.lock")


def read_pid_file(env: str = ENV_DEFAULT) -> dict | None:
    """Read and parse the PID file.

    Returns:
        Dict with pid, port, project_id, env, started_at or None if not found.
    """
    pid_path = get_pid_path(env)
    if not os.path.exists(pid_path):
        return None
    try:
        with open(pid_path) as f:
            data = json.load(f)
            data.setdefault("env", env)
            return data
    except (json.JSONDecodeError, OSError):
        return None


def write_pid_file(pid: int, port: int, project_id: str, env: str = ENV_DEFAULT) -> None:
    """Write the PID file atomically."""
    pid_path = get_pid_path(env)
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)
    data = {
        "pid": pid,
        "port": port,
        "project_id": project_id,
        "env": env,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp_path = pid_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f)
    os.replace(tmp_path, pid_path)


def remove_pid_file(env: str = ENV_DEFAULT) -> None:
    """Remove the PID file."""
    try:
        os.unlink(get_pid_path(env))
    except FileNotFoundError:
        pass


def is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def is_port_available(port: int, host: str = DEFAULT_HOST) -> bool:
    """Check if a port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            return True
    except OSError:
        return False


def find_available_port(preferred: int = DEFAULT_PORT, max_retries: int = MAX_PORT_RETRIES) -> int:
    """Find an available port starting from preferred.

    Args:
        preferred: Preferred port number
        max_retries: Number of ports to try (preferred, preferred+1, ...)

    Returns:
        Available port number

    Raises:
        RuntimeError: If no port is available in the range
    """
    for offset in range(max_retries):
        port = preferred + offset
        if is_port_available(port):
            return port
    raise RuntimeError(
        f"No available port in range {preferred}-{preferred + max_retries - 1}"
    )


def get_server_url(env: str = ENV_DEFAULT) -> str | None:
    """Get the running server's URL from PID file.

    Returns:
        Server URL (e.g., "http://127.0.0.1:8765") or None if not running.
    """
    info = read_pid_file(env)
    if info and is_process_alive(info["pid"]):
        return f"http://{DEFAULT_HOST}:{info['port']}"
    # Stale PID file - clean up
    if info:
        remove_pid_file(env)
    return None


def check_health(port: int, timeout: float = 2.0) -> bool:
    """Check if the server is healthy by hitting the health endpoint."""
    try:
        import urllib.request
        url = f"http://{DEFAULT_HOST}:{port}/api/v1/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "ok"
    except Exception:
        return False


def start_server(
    project_id: str = "default",
    port: int | None = None,
    workspace: str | None = None,
    wait: bool = True,
    env: str = ENV_DEFAULT,
) -> dict | None:
    """Start the ai server as a background process.

    Uses file locking to prevent race conditions when multiple
    CLI commands try to auto-start simultaneously.

    Args:
        project_id: Project identifier
        port: Preferred port (uses env-specific default if None)
        workspace: Workspace path
        wait: Whether to wait for health check
        env: Environment name ("default", "test", etc.)

    Returns:
        PID file info dict or None on failure
    """
    # Check if already running
    existing = get_server_url(env)
    if existing:
        return read_pid_file(env)

    lock_path = get_lock_path(env)
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)

    lock_fd = None
    try:
        # Acquire file lock (non-blocking first, then blocking with timeout)
        lock_fd = open(lock_path, "w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Another process is starting the server - wait for it
            logger.debug("Another process is starting the server, waiting...")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            # After acquiring lock, server may already be running
            existing = get_server_url(env)
            if existing:
                return read_pid_file(env)

        # Re-check after acquiring lock
        existing = get_server_url(env)
        if existing:
            return read_pid_file(env)

        # Find available port
        preferred = port or _default_port_for_env(env)
        try:
            actual_port = find_available_port(preferred)
        except RuntimeError as e:
            logger.error("Failed to find available port: %s", e)
            return None

        # Start the server process
        cmd = [
            sys.executable, "-m", "agentic_inquiry.server.run",
            "--port", str(actual_port),
            "--project-id", project_id,
            "--env", env,
        ]
        if workspace:
            cmd.extend(["--workspace", workspace])

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Write PID file immediately
        write_pid_file(proc.pid, actual_port, project_id, env=env)

        if wait:
            # Wait for health check
            deadline = time.monotonic() + HEALTH_CHECK_TIMEOUT
            while time.monotonic() < deadline:
                if check_health(actual_port, timeout=1.0):
                    logger.info(
                        "ai server started: env=%s pid=%d port=%d project=%s",
                        env, proc.pid, actual_port, project_id,
                    )
                    return read_pid_file(env)
                # Check if process died
                if proc.poll() is not None:
                    logger.error("Server process exited with code %d", proc.returncode)
                    remove_pid_file(env)
                    return None
                time.sleep(HEALTH_CHECK_INTERVAL)

            logger.warning("Server started but health check timed out")

        return read_pid_file(env)

    except Exception:
        logger.exception("Failed to start server")
        return None
    finally:
        if lock_fd:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            except Exception:
                pass


def stop_server(env: str = ENV_DEFAULT) -> bool:
    """Stop the running ai server.

    Returns:
        True if server was stopped, False if not running.
    """
    info = read_pid_file(env)
    if not info:
        return False

    pid = info["pid"]
    if not is_process_alive(pid):
        remove_pid_file(env)
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for graceful shutdown (up to 5s)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not is_process_alive(pid):
                remove_pid_file(env)
                logger.info("ai server stopped (env=%s pid=%d)", env, pid)
                return True
            time.sleep(0.2)
        # Force kill
        os.kill(pid, signal.SIGKILL)
        remove_pid_file(env)
        logger.warning("ai server force-killed (env=%s pid=%d)", env, pid)
        return True
    except ProcessLookupError:
        remove_pid_file(env)
        return False


def server_status(env: str = ENV_DEFAULT) -> dict:
    """Get the current server status.

    Returns:
        Status dict with running, env, pid, port, project_id, uptime fields.
    """
    info = read_pid_file(env)
    if not info:
        return {"running": False, "env": env}

    pid = info["pid"]
    if not is_process_alive(pid):
        remove_pid_file(env)
        return {"running": False, "env": env, "stale_pid_cleaned": True}

    # Check health
    healthy = check_health(info["port"], timeout=2.0)

    return {
        "running": True,
        "healthy": healthy,
        "env": env,
        "pid": pid,
        "port": info["port"],
        "project_id": info.get("project_id", "unknown"),
        "started_at": info.get("started_at", "unknown"),
    }


def ensure_server(
    project_id: str = "default",
    workspace: str | None = None,
    env: str = ENV_DEFAULT,
) -> str | None:
    """Ensure the server is running and return its URL.

    This is the main entry point for CLI commands that need the server.
    Auto-starts the server if not running.

    Args:
        project_id: Project identifier
        workspace: Workspace path
        env: Environment name

    Returns:
        Server URL or None if failed to start
    """
    url = get_server_url(env)
    if url:
        return url

    info = start_server(project_id=project_id, workspace=workspace, wait=True, env=env)
    if info:
        return f"http://{DEFAULT_HOST}:{info['port']}"
    return None


def all_servers_status() -> list[dict]:
    """Get status of all known server instances.

    Scans for PID files matching server*.pid pattern.
    """
    ai_home = get_agv_home()
    results = []
    if not os.path.isdir(ai_home):
        return results

    for name in os.listdir(ai_home):
        if name.startswith("server") and name.endswith(".pid"):
            # Extract env from filename: server.pid → "default", server-test.pid → "test"
            if name == "server.pid":
                env = ENV_DEFAULT
            else:
                env = name.removeprefix("server-").removesuffix(".pid")
            results.append(server_status(env))
    return results
