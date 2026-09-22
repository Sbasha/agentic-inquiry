"""GCP deploy orchestrator for Agent-Vault."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agent_vault.cli.deploy.base import (
    DEPLOY_DIR,
    DeployState,
    DeployStep,
    generate_api_key,
    run_shell_script,
    smoke_test,
)

logger = logging.getLogger("agv.deploy.gcp")

# Path to the GCP deploy shell script (relative to repo root)
_GCP_SCRIPT_REL = "scripts/deploy/gcp-deploy.sh"


@dataclass
class GCPDeployConfig:
    """Configuration for a GCP Agent-Vault deployment.

    Attributes:
        project: GCP project ID (required)
        region: GCP region (default: us-central1)
        alloydb_cluster: AlloyDB cluster ID
        alloydb_instance: AlloyDB primary instance ID
        alloydb_password: AlloyDB postgres user password (required)
        service_name: Cloud Run service name
        image_tag: Container image tag
        sa_name: Service account short name
        db_user: AlloyDB database user
        db_name: AlloyDB database name
    """

    project: str
    alloydb_password: str
    region: str = "us-central1"
    alloydb_cluster: str = "agv-cluster"
    alloydb_instance: str = "agv-primary"
    service_name: str = "agent-vault"
    image_tag: str = "latest"
    sa_name: str = "agv-run"
    db_user: str = "postgres"
    db_name: str = "agent-vault"
    extra_env: dict[str, str] = field(default_factory=dict)


class GCPDeployer:
    """Orchestrates Agent-Vault deployment to GCP.

    Delegates the heavy lifting to ``scripts/deploy/gcp-deploy.sh`` via
    ``run_shell_script()``, tracking each step in a ``DeployState`` resume file
    so interrupted deploys can be retried without re-running completed steps.

    Steps:
        1. check_prerequisites   — gcloud + docker available, auth valid
        2. create_alloydb        — AlloyDB cluster + primary instance
        3. configure_iam         — service account, roles, Secret Manager
        4. initialize_embeddings — AlloyDB AI extension + embedding config note
        5. build_container       — Docker build + push to Artifact Registry
        6. deploy_cloud_run      — Cloud Run service create/update
        7. configure_auth        — store API key, verify Secret Manager binding
        8. smoke_test            — poll /api/v1/health until 200

    Example::

        config = GCPDeployConfig(
            project="my-gcp-project",
            alloydb_password="s3cr3t",
        )
        deployer = GCPDeployer(config)
        state = deployer.deploy()
        print(f"Deployed to: {state.server_url}")
    """

    def __init__(
        self,
        config: GCPDeployConfig,
        deploy_dir: Optional[str] = None,
        script_path: Optional[str] = None,
    ) -> None:
        """Initialise the deployer.

        Args:
            config: GCP deployment configuration.
            deploy_dir: Directory for state files (default: ``.agv/deploy``).
            script_path: Explicit path to ``gcp-deploy.sh``.  When omitted,
                the file is resolved relative to the current working directory.
        """
        self._config = config
        self._deploy_dir = Path(deploy_dir or DEPLOY_DIR)
        self._script_path = script_path or str(Path.cwd() / _GCP_SCRIPT_REL)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deploy(self) -> DeployState:
        """Run the full GCP deployment.

        Returns:
            Completed ``DeployState`` with ``server_url`` populated.

        Raises:
            RuntimeError: If any deploy step fails.
        """
        state = self._load_or_create_state()

        api_key = state.api_key or generate_api_key()
        state.api_key = api_key

        env = self._build_env(api_key)

        logger.info("Starting GCP deploy for project=%s", self._config.project)

        result = run_shell_script(self._script_path, env=env)

        if result.returncode != 0:
            logger.error("GCP deploy script failed:\n%s", result.stderr)
            raise RuntimeError(
                f"GCP deploy script exited with code {result.returncode}.\n"
                f"stderr:\n{result.stderr}"
            )

        logger.info("GCP deploy script output:\n%s", result.stdout)

        # Read the service URL written by the script
        url_file = self._deploy_dir / "service-url.txt"
        server_url: Optional[str] = None
        if url_file.exists():
            server_url = url_file.read_text().strip()

        # Mark all 8 steps complete in state
        step_names = [
            ("check_prerequisites", "Check prerequisites"),
            ("create_alloydb", "Create AlloyDB cluster and instance"),
            ("configure_iam", "Configure IAM and service account"),
            ("initialize_embeddings", "Initialize AlloyDB AI embeddings"),
            ("build_container", "Build and push container image"),
            ("deploy_cloud_run", "Deploy to Cloud Run"),
            ("configure_auth", "Configure authentication"),
            ("smoke_test", "Smoke test health endpoint"),
        ]

        # Sync step state from marker files
        state.steps = [
            DeployStep(
                name=name,
                description=desc,
                completed=self._step_marker_exists(f"{i+1:02d}-{name.split('_')[0]}"),
            )
            for i, (name, desc) in enumerate(step_names)
        ]

        state.server_url = server_url
        state.save(self._deploy_dir / "gcp-state.json")

        logger.info("GCP deploy complete. Service URL: %s", server_url)
        return state

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_or_create_state(self) -> DeployState:
        """Load existing resume state or create a fresh one."""
        state_path = self._deploy_dir / "gcp-state.json"
        state = DeployState.load(state_path)
        if state is None:
            state = DeployState(
                provider="gcp",
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                steps=[],
                api_key="",
                server_url=None,
            )
        return state

    def _build_env(self, api_key: str) -> dict[str, str]:
        """Build environment variables for the deploy script."""
        env: dict[str, str] = {
            "agv_GCP_PROJECT": self._config.project,
            "agv_GCP_REGION": self._config.region,
            "agv_ALLOYDB_CLUSTER": self._config.alloydb_cluster,
            "agv_ALLOYDB_INSTANCE": self._config.alloydb_instance,
            "agv_ALLOYDB_PASSWORD": self._config.alloydb_password,
            "agv_API_KEY": api_key,
            "agv_IMAGE_TAG": self._config.image_tag,
            "agv_SERVICE_NAME": self._config.service_name,
            "agv_SA_NAME": self._config.sa_name,
            "agv_DB_USER": self._config.db_user,
            "agv_DB_NAME": self._config.db_name,
            "agv_DEPLOY_STATE_DIR": str(self._deploy_dir),
        }
        env.update(self._config.extra_env)
        return env

    def _step_marker_exists(self, step_prefix: str) -> bool:
        """Return True if any step marker file starting with step_prefix exists."""
        for f in self._deploy_dir.glob(f"step-{step_prefix}*.done"):
            if f.exists():
                return True
        return False
