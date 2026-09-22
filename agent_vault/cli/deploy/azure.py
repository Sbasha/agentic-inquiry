"""Azure deploy orchestrator for Agent-Vault.

Wraps ``scripts/deploy/azure-deploy.sh`` to provision an Azure
Database for PostgreSQL Flexible Server + Container Registry +
Container Apps deployment. The script is the supported path; the
manual equivalent (CLI snippets, ``azure_ai`` extension wiring,
``embedding_strategy`` choices, troubleshooting) is documented
end-to-end in ``docs/backends/azure.md``. If you're operating without
the script — restricted RBAC, sovereign-cloud region, IaC migration —
that doc has the manual recipe.
"""

from __future__ import annotations

import logging
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
)

logger = logging.getLogger("agv.deploy.azure")

_AZURE_SCRIPT_REL = "scripts/deploy/azure-deploy.sh"


@dataclass
class AzureDeployConfig:
    """Configuration for a Agent-Vault Azure deployment.

    Attributes:
        subscription_id: Azure subscription ID (required)
        resource_group: Azure resource group name (required)
        pg_password: PostgreSQL admin password (required)
        location: Azure region (default: eastus)
        pg_server_name: PostgreSQL Flexible Server name
        pg_sku: PostgreSQL SKU name
        acr_name: Azure Container Registry name
        service_name: Container App name
        image_tag: Container image tag
        ca_env_name: Container Apps Environment name
        db_name: Database name
        db_user: Database admin user
    """

    subscription_id: str
    resource_group: str
    pg_password: str
    location: str = "eastus"
    pg_server_name: str = "agv-postgres"
    pg_sku: str = "Standard_B1ms"
    acr_name: str = "agvimages"
    service_name: str = "agent-vault"
    image_tag: str = "latest"
    ca_env_name: str = "agv-env"
    db_name: str = "agent-vault"
    db_user: str = "agvadmin"
    extra_env: dict[str, str] = field(default_factory=dict)


class AzureDeployer:
    """Orchestrates Agent-Vault deployment to Azure.

    Delegates to ``scripts/deploy/azure-deploy.sh`` via ``run_shell_script()``,
    tracking progress in a ``DeployState`` resume file.

    Steps:
        1. check_prerequisites   — az CLI + docker + authentication
        2. create_resource_group — ensure resource group exists
        3. create_postgres       — PostgreSQL Flexible Server + database
        4. configure_identity    — Managed Identity + Key Vault secret
        5. build_container       — Docker build + push to ACR
        6. deploy_container_apps — Container Apps deployment
        7. smoke_test            — poll /api/v1/health until 200

    Example::

        config = AzureDeployConfig(
            subscription_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            resource_group="agv-prod-rg",
            pg_password="s3cr3t",
        )
        deployer = AzureDeployer(config)
        state = deployer.deploy()
        print(f"Deployed to: {state.server_url}")
    """

    def __init__(
        self,
        config: AzureDeployConfig,
        deploy_dir: Optional[str] = None,
        script_path: Optional[str] = None,
    ) -> None:
        """Initialise the deployer.

        Args:
            config: Azure deployment configuration.
            deploy_dir: Directory for state files (default: ``.agv/deploy``).
            script_path: Explicit path to ``azure-deploy.sh``.
        """
        self._config = config
        self._deploy_dir = Path(deploy_dir or DEPLOY_DIR)
        self._script_path = script_path or str(Path.cwd() / _AZURE_SCRIPT_REL)

    def deploy(self) -> DeployState:
        """Run the full Azure deployment.

        Returns:
            Completed ``DeployState`` with ``server_url`` populated.

        Raises:
            RuntimeError: If any deploy step fails.
        """
        state = self._load_or_create_state()
        api_key = state.api_key or generate_api_key()
        state.api_key = api_key

        env = self._build_env(api_key)
        logger.info(
            "Starting Azure deploy for subscription=%s resource_group=%s",
            self._config.subscription_id,
            self._config.resource_group,
        )

        result = run_shell_script(self._script_path, env=env)

        if result.returncode != 0:
            logger.error("Azure deploy script failed:\n%s", result.stderr)
            raise RuntimeError(
                f"Azure deploy script exited with code {result.returncode}.\n"
                f"stderr:\n{result.stderr}"
            )

        logger.info("Azure deploy script output:\n%s", result.stdout)

        url_file = self._deploy_dir / "service-url.txt"
        server_url: Optional[str] = url_file.read_text().strip() if url_file.exists() else None

        step_names = [
            ("check_prerequisites", "Check prerequisites"),
            ("create_resource_group", "Ensure Azure resource group"),
            ("create_postgres", "Create PostgreSQL Flexible Server"),
            ("configure_identity", "Configure Managed Identity and Key Vault"),
            ("build_container", "Build and push container to ACR"),
            ("deploy_container_apps", "Deploy to Azure Container Apps"),
            ("smoke_test", "Smoke test health endpoint"),
        ]

        state.steps = [
            DeployStep(
                name=name,
                description=desc,
                completed=self._step_marker_exists(f"{i+1:02d}"),
            )
            for i, (name, desc) in enumerate(step_names)
        ]

        state.server_url = server_url
        state.save(self._deploy_dir / "azure-state.json")
        logger.info("Azure deploy complete. Service URL: %s", server_url)
        return state

    def _load_or_create_state(self) -> DeployState:
        state_path = self._deploy_dir / "azure-state.json"
        state = DeployState.load(state_path)
        if state is None:
            state = DeployState(
                provider="azure",
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                steps=[],
                api_key="",
                server_url=None,
            )
        return state

    def _build_env(self, api_key: str) -> dict[str, str]:
        env: dict[str, str] = {
            "agv_AZURE_SUBSCRIPTION_ID": self._config.subscription_id,
            "agv_AZURE_RESOURCE_GROUP": self._config.resource_group,
            "agv_AZURE_LOCATION": self._config.location,
            "agv_PG_SERVER_NAME": self._config.pg_server_name,
            "agv_PG_SKU": self._config.pg_sku,
            "agv_PG_PASSWORD": self._config.pg_password,
            "agv_ACR_NAME": self._config.acr_name,
            "agv_SERVICE_NAME": self._config.service_name,
            "agv_IMAGE_TAG": self._config.image_tag,
            "agv_CA_ENV_NAME": self._config.ca_env_name,
            "agv_DB_NAME": self._config.db_name,
            "agv_DB_USER": self._config.db_user,
            "agv_API_KEY": api_key,
            "agv_DEPLOY_STATE_DIR": str(self._deploy_dir),
        }
        env.update(self._config.extra_env)
        return env

    def _step_marker_exists(self, step_prefix: str) -> bool:
        for f in self._deploy_dir.glob(f"step-{step_prefix}*.done"):
            if f.exists():
                return True
        return False
