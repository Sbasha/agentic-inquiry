"""Cloud SQL Proxy management for Agent-Vault.

This module handles automatic startup and management of the Cloud SQL Proxy
when a PostgreSQL/CloudSQL configuration is detected.

Auto-start behavior:
- 'agv' (default env): Auto-start if CloudSQL configured
- 'agv-test' prefix: Never auto-start (test isolation)
- Custom envs: Based on services.auto_start_proxy config flag
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from agent_vault.config import Config, ServicesConfig

logger = logging.getLogger(__name__)

# Process reference for cleanup
_proxy_process: Optional[subprocess.Popen] = None


def find_cloudsql_backend(config: Config) -> Optional[dict[str, Any]]:
    """Find CloudSQL or AlloyDB backend configuration if present.

    Searches the config for a backend that requires a proxy connection
    (CloudSQL via cloud-sql-proxy or AlloyDB via alloydb-auth-proxy).

    Args:
        config: Loaded configuration

    Returns:
        Backend config dict or None if no CloudSQL/AlloyDB backend found
    """
    backends = config.storage.backends
    if not backends:
        return None

    from agent_vault.storage.capabilities import get_capabilities_for_backend

    for name, backend in backends.items():
        backend_type = backend.get("type", "")
        caps = get_capabilities_for_backend(backend_type)

        # Check if this backend requires a proxy (AlloyDB or CloudSQL)
        if caps.requires_proxy:
            return {
                "name": name,
                "proxy_type": caps.proxy_type or backend_type,
                **backend,
            }

        # Legacy heuristic: PostgreSQL with CloudSQL-style connection
        if backend_type == "postgresql":
            conn_str = backend.get("connection_string", "")
            if "localhost:5433" in conn_str or "127.0.0.1:5433" in conn_str:
                return {
                    "name": name,
                    "connection_string": conn_str,
                    "proxy_type": "cloudsql",
                    **backend,
                }
            if backend.get("cloudsql") or backend.get("cloud_sql"):
                return {
                    "name": name,
                    "connection_string": conn_str,
                    "proxy_type": "cloudsql",
                    **backend,
                }

    return None


def find_proxy_binary(proxy_type: str = "cloudsql") -> Optional[Path]:
    """Find the proxy binary for CloudSQL or AlloyDB.

    Args:
        proxy_type: Either "cloudsql" or "alloydb"

    Searches in standard locations:
    1. PATH (via which/shutil.which)
    2. ~/google-cloud-sdk/bin/
    3. /usr/local/bin/
    4. ~/.local/bin/

    Returns:
        Path to binary or None if not found
    """
    if proxy_type == "alloydb":
        binary_name = "alloydb-auth-proxy"
    else:
        binary_name = "cloud-sql-proxy"

    # Check PATH first
    proxy_path = shutil.which(binary_name)
    if proxy_path:
        return Path(proxy_path)

    # Check common locations
    common_paths = [
        Path.home() / "google-cloud-sdk" / "bin" / binary_name,
        Path(f"/usr/local/bin/{binary_name}"),
        Path.home() / ".local" / "bin" / binary_name,
        Path(f"/opt/homebrew/bin/{binary_name}"),  # macOS Homebrew
    ]

    for path in common_paths:
        if path.exists() and os.access(path, os.X_OK):
            return path

    return None


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is already in use.

    Args:
        port: Port number to check
        host: Host to check (default localhost)

    Returns:
        True if port is in use
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except socket.error:
            return True


def is_proxy_running(port: int = 5433) -> bool:
    """Check if Cloud SQL Proxy is already running.

    Checks both process name and port availability.

    Args:
        port: Port the proxy should be listening on

    Returns:
        True if proxy appears to be running
    """
    # Check if port is in use (proxy listening)
    if is_port_in_use(port):
        logger.debug("Port %d is in use, proxy may be running", port)
        return True

    # Also check for running process (both cloud-sql-proxy and alloydb-auth-proxy)
    try:
        for proxy_name in ["cloud-sql-proxy", "alloydb-auth-proxy"]:
            result = subprocess.run(
                ["pgrep", "-f", proxy_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                logger.debug("Found running %s process(es): %s", proxy_name, result.stdout.strip())
                return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return False


def start_cloud_sql_proxy(
    connection_name: str,
    port: int = 5433,
    log_path: Optional[str] = None,
    binary_path: Optional[str] = None,
    timeout: int = 30,
    use_public_ip: bool = False,
) -> bool:

    """Start the Cloud SQL Proxy in the background.

    Args:
        connection_name: Full Cloud SQL connection name (project:region:instance)
        port: Local port to listen on
        binary_path: Path to proxy binary (auto-detected if None)
        log_path: Path to write proxy logs (optional)
        timeout: Seconds to wait for proxy to start

    Returns:
        True if proxy started successfully, False otherwise
    """
    global _proxy_process

    if not connection_name:
        logger.error("No connection_name provided for Cloud SQL Proxy")
        return False

    # Check if already running
    if is_proxy_running(port):
        logger.info("Cloud SQL Proxy already running on port %d", port)
        return True

    # Find binary
    proxy_bin = Path(binary_path) if binary_path else find_proxy_binary()
    if not proxy_bin or not proxy_bin.exists():
        if "alloydb" in str(proxy_bin or "") or "alloydb" in connection_name:
            binary_name = "alloydb-auth-proxy"
            install_cmd = "curl -o alloydb-auth-proxy https://storage.googleapis.com/alloydb-auth-proxy/v1.12.0/alloydb-auth-proxy.darwin.arm64"
        else:
            binary_name = "cloud-sql-proxy"
            install_cmd = "curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.8.0/cloud-sql-proxy.darwin.arm64"
            
        logger.error(
            f"{binary_name} binary not found. Install with:\n"
            f"  {install_cmd}\n"
            f"  chmod +x {binary_name} && mv {binary_name} /usr/local/bin/"
        )
        return False

    # Build command
    is_alloydb = "alloydb" in str(proxy_bin).lower() or "alloydb" in connection_name.lower()

    if is_alloydb:
        cmd = [
            str(proxy_bin),
            f"--port={port}",
            "--address=127.0.0.1",
        ]
        if use_public_ip:
            cmd.append("--public-ip")
        cmd.append(connection_name)
    else:
        cmd = [
            str(proxy_bin),
            f"--port={port}",
            connection_name
        ]

    logger.info("Starting %s Proxy: %s", "AlloyDB" if is_alloydb else "Cloud SQL", " ".join(cmd))


    try:
        # Prepare log file if specified
        log_file = None
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "a")

        # Start proxy in background
        _proxy_process = subprocess.Popen(
            cmd,
            stdout=log_file or subprocess.DEVNULL,
            stderr=log_file or subprocess.DEVNULL,
            start_new_session=True  # Detach from terminal
        )

        # Wait for proxy to be ready
        for i in range(timeout):
            if is_port_in_use(port):
                logger.info("Cloud SQL Proxy started successfully on port %d (PID: %d)", port, _proxy_process.pid)
                return True

            # Check if process exited
            if _proxy_process.poll() is not None:
                logger.error("Cloud SQL Proxy exited unexpectedly with code %d", _proxy_process.returncode)
                return False

            asyncio.get_event_loop().run_until_complete(asyncio.sleep(1))

        logger.error("Timeout waiting for Cloud SQL Proxy to start")
        return False

    except Exception as e:
        logger.exception("Failed to start Cloud SQL Proxy: %s", e)
        return False


def stop_cloud_sql_proxy() -> bool:
    """Stop the Cloud SQL Proxy if we started it.

    Returns:
        True if stopped successfully
    """
    global _proxy_process

    if _proxy_process is None:
        return True

    try:
        logger.info("Stopping Cloud SQL Proxy (PID: %d)", _proxy_process.pid)
        _proxy_process.terminate()
        try:
            _proxy_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _proxy_process.kill()
        _proxy_process = None
        return True
    except Exception as e:
        logger.warning("Error stopping Cloud SQL Proxy: %s", e)
        return False


async def ensure_cloud_sql_proxy(
    config: Config,
    env_name: str = "default",
    force: bool = False
) -> bool:
    """Ensure Cloud SQL Proxy is running if needed.

    Checks configuration and environment to determine if proxy should
    be started, then starts it if needed.

    Args:
        config: Loaded configuration
        env_name: Current environment name (for auto-start logic)
        force: Force start even if auto-start is disabled

    Returns:
        True if proxy is running (or not needed), False on failure
    """
    from agent_vault.cli.env_resolver import is_test_environment, should_auto_start_proxy

    # Check if CloudSQL/AlloyDB backend is configured
    cloudsql_backend = find_cloudsql_backend(config)
    if not cloudsql_backend:
        logger.debug("No CloudSQL/AlloyDB backend configured, proxy not needed")
        return True

    proxy_type = cloudsql_backend.get("proxy_type", "cloudsql")

    # Check if we should auto-start
    services_config = config.services
    should_start = force or (
        services_config.auto_start_proxy and
        should_auto_start_proxy(env_name, has_cloudsql_config=True)
    )

    # AlloyDB uses port 5432 by default, CloudSQL uses 5433
    default_port = 5432 if proxy_type == "alloydb" else 5433

    if not should_start:
        # Check if proxy is needed but not auto-started
        proxy_port = services_config.proxy.port or default_port
        if not is_proxy_running(proxy_port):
            proxy_binary = "alloydb-auth-proxy" if proxy_type == "alloydb" else "cloud-sql-proxy"
            logger.warning(
                "%s configured but proxy not running and auto-start disabled. "
                "Start manually: %s --port=%d %s",
                proxy_type.upper(),
                proxy_binary,
                proxy_port,
                services_config.proxy.connection_name or "<connection-name>"
            )
        return True

    # Get proxy settings
    connection_name = services_config.proxy.connection_name
    if not connection_name:
        logger.warning("No proxy connection_name configured in services.proxy")
        return False

    port = services_config.proxy.port or default_port
    binary_path = services_config.proxy.binary_path

    # Determine log path
    from agent_vault.cli.env_resolver import get_global_dir
    global_dir = get_global_dir()
    log_path = global_dir / "envs" / env_name / "logs" / "proxy.log"

    # Find correct proxy binary
    if not binary_path:
        proxy_bin = find_proxy_binary(proxy_type)
        binary_path = str(proxy_bin) if proxy_bin else None

    # Start proxy
    return start_cloud_sql_proxy(
        connection_name=connection_name,
        port=port,
        binary_path=binary_path,
        log_path=log_path,
        timeout=services_config.startup_timeout,
        use_public_ip=services_config.proxy.use_public_ip
    )


def register_cleanup_handler():
    """Register signal handlers to cleanup proxy on exit."""
    def cleanup_handler(signum, frame):
        stop_cloud_sql_proxy()
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup_handler)
    signal.signal(signal.SIGINT, cleanup_handler)


__all__ = [
    "find_cloudsql_backend",
    "find_proxy_binary",
    "is_proxy_running",
    "start_cloud_sql_proxy",
    "stop_cloud_sql_proxy",
    "ensure_cloud_sql_proxy",
    "register_cleanup_handler",
]
