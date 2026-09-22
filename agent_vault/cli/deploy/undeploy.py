"""Undeploy orchestrator — tears down cloud deployments from saved state."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from agent_vault.cli.deploy.base import (
    DEPLOY_DIR,
    DeployState,
    run_shell_script,
)

logger = logging.getLogger("agv.deploy.undeploy")

# Paths to per-cloud undeploy scripts (relative to repo root)
_UNDEPLOY_SCRIPTS: dict[str, str] = {
    "gcp": "scripts/deploy/gcp-undeploy.sh",
    "aws": "scripts/deploy/aws-undeploy.sh",
    "azure": "scripts/deploy/azure-undeploy.sh",
}


class Undeployer:
    """Tears down a Agent-Vault cloud deployment.

    Reads the ``DeployState`` JSON written by the appropriate deployer, builds
    the environment expected by the per-cloud undeploy shell script, and
    delegates to that script via ``run_shell_script()``.

    Example::

        # Undeploy an existing GCP deployment
        undeployer = Undeployer(provider="gcp")
        undeployer.undeploy()

        # Pass override env vars (e.g. different project or region)
        undeployer = Undeployer(
            provider="gcp",
            extra_env={"agv_GCP_PROJECT": "other-project"},
        )
        undeployer.undeploy()
    """

    def __init__(
        self,
        provider: str,
        deploy_dir: Optional[str] = None,
        script_path: Optional[str] = None,
        extra_env: Optional[dict[str, str]] = None,
    ) -> None:
        """Initialise the undeployer.

        Args:
            provider: Cloud provider name: ``"gcp"``, ``"aws"``, or ``"azure"``.
            deploy_dir: Directory containing the deploy state file and step
                markers (default: ``.agv/deploy``).
            script_path: Explicit path to the undeploy shell script.  When
                omitted, resolved from ``_UNDEPLOY_SCRIPTS[provider]``.
            extra_env: Additional environment variables forwarded to the script.

        Raises:
            ValueError: If ``provider`` is not a recognised cloud provider.
        """
        if provider not in _UNDEPLOY_SCRIPTS:
            raise ValueError(
                f"Unknown provider '{provider}'. "
                f"Supported: {sorted(_UNDEPLOY_SCRIPTS.keys())}"
            )
        self._provider = provider
        self._deploy_dir = Path(deploy_dir or DEPLOY_DIR)
        self._script_path = script_path or str(
            Path.cwd() / _UNDEPLOY_SCRIPTS[provider]
        )
        self._extra_env = extra_env or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def undeploy(self) -> None:
        """Run the undeploy script for the configured provider.

        Loads the deploy state (if present) to extract environment variables
        needed by the undeploy script, then delegates to the shell script.

        Raises:
            RuntimeError: If the undeploy script exits non-zero.
        """
        state = self._load_state()
        env = self._build_env(state)

        logger.info(
            "Starting undeploy for provider=%s deploy_dir=%s",
            self._provider,
            self._deploy_dir,
        )

        result = run_shell_script(self._script_path, env=env)

        if result.returncode != 0:
            logger.error("Undeploy script failed:\n%s", result.stderr)
            raise RuntimeError(
                f"Undeploy script for '{self._provider}' exited with code "
                f"{result.returncode}.\nstderr:\n{result.stderr}"
            )

        logger.info("Undeploy complete for provider=%s", self._provider)
        if result.stdout:
            logger.info("Script output:\n%s", result.stdout)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_state(self) -> Optional[DeployState]:
        """Load the deploy state from the state file, or None if missing."""
        state_path = self._deploy_dir / f"{self._provider}-state.json"
        state = DeployState.load(state_path)
        if state is None:
            logger.warning(
                "No deploy state found at %s — proceeding without state",
                state_path,
            )
        return state

    def _build_env(self, state: Optional[DeployState]) -> dict[str, str]:
        """Build environment variables for the undeploy script.

        Merges state-derived values (server URL, API key) with any extra_env
        overrides provided at construction time.

        Args:
            state: Optional loaded DeployState.

        Returns:
            Environment variable dict forwarded to the undeploy script.
        """
        env: dict[str, str] = {
            "agv_DEPLOY_STATE_DIR": str(self._deploy_dir),
        }

        # Provider-specific env from state
        if state is not None and state.server_url:
            env["agv_SERVER_URL"] = state.server_url

        env.update(self._extra_env)
        return env
