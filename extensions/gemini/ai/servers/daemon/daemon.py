"""ai Daemon Service - Lifecycle management.

Manages the daemon process: PID file, Unix socket, signal handling,
graceful startup and shutdown. Lazy project initialization on first request.
"""

import asyncio
import hashlib
import logging
import os
import signal
import sys
from pathlib import Path

import yaml
from aiohttp import web

logger = logging.getLogger("ai.daemon")


class agvDaemon:
    """Persistent daemon for ai hook support.

    Manages warm state (DB connections, embedder, caches) and serves
    hook requests over a Unix domain socket.
    """

    def __init__(self, workspace: str, config_overrides: dict | None = None) -> None:
        self.workspace = os.path.abspath(workspace)
        self.project_id = hashlib.sha256(
            self.workspace.encode()
        ).hexdigest()[:16]

        # Paths
        self.ai_home = os.environ.get(
            "INQUIRY_HOME", os.path.expanduser("~/.agentic-inquiry")
        )
        self.socket_path = os.path.join(
            self.ai_home, f"daemon-{self.project_id}.sock"
        )
        self.pid_path = os.path.join(
            self.ai_home, f"daemon-{self.project_id}.pid"
        )

        # Config
        self.config = self._load_config(config_overrides)

        # State
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.UnixSite | None = None
        self._orchestrator = None
        self._shutdown_event = asyncio.Event()
        self._started = False

    def _load_config(self, overrides: dict | None = None) -> dict:
        """Load daemon configuration from defaults + overrides."""
        defaults_path = (
            Path(__file__).parent.parent.parent
            / "config"
            / "daemon-defaults.yaml"
        )
        config = {}
        if defaults_path.exists():
            with open(defaults_path) as f:
                config = yaml.safe_load(f) or {}

        config = config.get("daemon", {})

        if overrides:
            self._deep_merge(config, overrides)

        return config

    @staticmethod
    def _deep_merge(base: dict, overlay: dict) -> dict:
        """Deep merge overlay into base dict."""
        for key, value in overlay.items():
            if (
                key in base
                and isinstance(base[key], dict)
                and isinstance(value, dict)
            ):
                agvDaemon._deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    async def start(self) -> None:
        """Start the daemon service."""
        # Ensure ai home exists
        os.makedirs(self.ai_home, exist_ok=True)

        # Check for stale socket/PID
        await self._cleanup_stale()

        # Write PID
        with open(self.pid_path, "w") as f:
            f.write(str(os.getpid()))

        # Create the aiohttp app
        from .api import create_app

        self._app = create_app(self)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        # Create Unix socket site
        self._site = web.UnixSite(self._runner, self.socket_path)
        await self._site.start()

        # Set socket permissions (owner only)
        perms = self.config.get("security", {}).get(
            "socket_permissions", 0o600
        )
        os.chmod(self.socket_path, perms)

        self._started = True
        logger.info(
            "ai daemon started: workspace=%s socket=%s pid=%d",
            self.workspace,
            self.socket_path,
            os.getpid(),
        )

        # Register signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._signal_shutdown)

    def _signal_shutdown(self) -> None:
        """Handle shutdown signals."""
        logger.info("Received shutdown signal")
        self._shutdown_event.set()

    async def run_forever(self) -> None:
        """Run until shutdown signal received."""
        await self._shutdown_event.wait()
        await self.stop()

    async def stop(self) -> None:
        """Gracefully stop the daemon."""
        if not self._started:
            return

        logger.info("Stopping ai daemon...")

        # Shutdown orchestrator (flushes caches, closes connections)
        if self._orchestrator:
            try:
                await self._orchestrator.shutdown()
            except Exception:
                logger.exception("Error during orchestrator shutdown")

        # Stop HTTP server
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

        # Remove socket and PID
        for path in (self.socket_path, self.pid_path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

        self._started = False
        logger.info("ai daemon stopped")

    async def _cleanup_stale(self) -> None:
        """Remove stale socket/PID from crashed daemon."""
        # Check PID file
        if os.path.exists(self.pid_path):
            try:
                with open(self.pid_path) as f:
                    old_pid = int(f.read().strip())
                # Check if process is still running
                os.kill(old_pid, 0)
                # Process exists - another daemon is running
                logger.warning(
                    "Daemon already running (pid=%d), stopping it",
                    old_pid,
                )
                try:
                    os.kill(old_pid, signal.SIGTERM)
                    await asyncio.sleep(1.0)
                except ProcessLookupError:
                    pass
            except (ProcessLookupError, ValueError):
                pass  # Process not running, clean up
            try:
                os.unlink(self.pid_path)
            except FileNotFoundError:
                pass

        # Remove stale socket
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass

    def get_orchestrator(self):
        """Get or lazily create the service orchestrator."""
        if self._orchestrator is None:
            from .orchestrator import ServiceOrchestrator

            self._orchestrator = ServiceOrchestrator(
                workspace=self.workspace,
                project_id=self.project_id,
                config=self.config,
            )
        return self._orchestrator

    @property
    def uptime_seconds(self) -> float:
        """Daemon uptime in seconds."""
        if not hasattr(self, "_start_time"):
            self._start_time = asyncio.get_event_loop().time()
        return asyncio.get_event_loop().time() - self._start_time
