"""Auto-provision delegation — route cloud-detected environments to deployers."""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from agent_vault.cli.cloud_detect import CloudContext

logger = logging.getLogger("agv.deploy.auto_provision")


def auto_provision_for_cloud(cloud_context: "CloudContext") -> bool:
    """Attempt to auto-provision Agent-Vault for the detected cloud.

    Called when ``agv_AUTO_PROVISION=1`` is set and the environment resolver
    detects that the process is running inside a cloud VM/container without a
    registered agv environment.

    Behaviour:
    - GCP: Creates a ``GCPDeployConfig`` from IMDS-detected project/region and
      environment variables, then runs ``GCPDeployer.deploy()``.
    - AWS: Creates an ``AWSDeployConfig`` from IMDS-detected account/region.
    - Azure: Creates an ``AzureDeployConfig`` from environment variables.

    The caller (``load_config_for_environment``) should catch ``RuntimeError``
    and fall back gracefully.

    Args:
        cloud_context: Detected cloud context from ``detect_cloud_context()``.

    Returns:
        True if auto-provision succeeded, False otherwise.

    Raises:
        RuntimeError: Propagated from the deployer if the deploy script fails.
    """
    provider = cloud_context.provider.lower()

    logger.info(
        "Auto-provisioning Agent-Vault for provider=%s project_id=%s region=%s",
        provider,
        cloud_context.project_id,
        cloud_context.region,
    )

    if provider == "gcp":
        return _provision_gcp(cloud_context)
    elif provider == "aws":
        return _provision_aws(cloud_context)
    elif provider == "azure":
        return _provision_azure(cloud_context)
    else:
        logger.warning("Auto-provision not supported for provider '%s'", provider)
        return False


def prompt_user_for_cloud_config(cloud_context: "CloudContext") -> Optional[str]:
    """Interactively prompt the user when a cloud environment is detected.

    Presents the detected cloud context and asks whether they want to deploy
    Agent-Vault using the detected configuration.  Only called when
    ``sys.stdin.isatty()`` is True and ``agv_AUTO_PROVISION`` is not set.

    Args:
        cloud_context: Detected cloud context from ``detect_cloud_context()``.

    Returns:
        ``"deploy"`` if user confirmed, ``"skip"`` to proceed without deploy,
        or ``None`` if TTY prompt was not possible.
    """
    provider = cloud_context.provider.upper()

    print(
        f"\n[agv] Cloud environment detected: {provider}"
        f" (project/account: {cloud_context.project_id or 'unknown'}"
        f", region: {cloud_context.region or 'unknown'})\n"
        f"Agent-Vault is not yet configured for this environment.\n"
    )

    try:
        answer = input(
            "Would you like to deploy Agent-Vault now? [y/N] "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return "skip"

    if answer in ("y", "yes"):
        print("[agv] Starting auto-provisioning...\n")
        return "deploy"

    print("[agv] Skipping deploy. Proceeding with detected config (may be incomplete).\n")
    return "skip"


# ──────────────────────────────────────────────────────────────────────────────
# Per-cloud provisioning helpers
# ──────────────────────────────────────────────────────────────────────────────


def _provision_gcp(cloud_context: "CloudContext") -> bool:
    """Auto-provision for GCP using IMDS-detected project and region."""
    from agent_vault.cli.deploy.gcp import GCPDeployer, GCPDeployConfig

    project = cloud_context.project_id or os.environ.get("agv_GCP_PROJECT", "")
    if not project:
        logger.error(
            "Cannot auto-provision GCP: project ID not available from IMDS or "
            "agv_GCP_PROJECT env var"
        )
        return False

    alloydb_password = os.environ.get("agv_ALLOYDB_PASSWORD", "")
    if not alloydb_password:
        logger.error(
            "Cannot auto-provision GCP: agv_ALLOYDB_PASSWORD not set"
        )
        return False

    config = GCPDeployConfig(
        project=project,
        alloydb_password=alloydb_password,
        region=cloud_context.region or "us-central1",
    )

    deployer = GCPDeployer(config)
    state = deployer.deploy()
    logger.info("GCP auto-provision complete. Service URL: %s", state.server_url)
    return True


def _provision_aws(cloud_context: "CloudContext") -> bool:
    """Auto-provision for AWS using IMDS-detected account and region."""
    from agent_vault.cli.deploy.aws import AWSDeployer, AWSDeployConfig

    account_id = cloud_context.project_id or os.environ.get("agv_AWS_ACCOUNT_ID", "")
    if not account_id:
        logger.error(
            "Cannot auto-provision AWS: account ID not available from IMDS or "
            "agv_AWS_ACCOUNT_ID env var"
        )
        return False

    rds_password = os.environ.get("agv_RDS_PASSWORD", "")
    if not rds_password:
        logger.error("Cannot auto-provision AWS: agv_RDS_PASSWORD not set")
        return False

    config = AWSDeployConfig(
        aws_account_id=account_id,
        rds_password=rds_password,
        region=cloud_context.region or "us-east-1",
    )

    deployer = AWSDeployer(config)
    state = deployer.deploy()
    logger.info("AWS auto-provision complete. Service URL: %s", state.server_url)
    return True


def _provision_azure(cloud_context: "CloudContext") -> bool:
    """Auto-provision for Azure using environment variables."""
    from agent_vault.cli.deploy.azure import AzureDeployer, AzureDeployConfig

    subscription_id = os.environ.get("agv_AZURE_SUBSCRIPTION_ID", "")
    resource_group = os.environ.get("agv_AZURE_RESOURCE_GROUP", "")
    pg_password = os.environ.get("agv_PG_PASSWORD", "")

    if not subscription_id:
        logger.error("Cannot auto-provision Azure: agv_AZURE_SUBSCRIPTION_ID not set")
        return False
    if not resource_group:
        logger.error("Cannot auto-provision Azure: agv_AZURE_RESOURCE_GROUP not set")
        return False
    if not pg_password:
        logger.error("Cannot auto-provision Azure: agv_PG_PASSWORD not set")
        return False

    config = AzureDeployConfig(
        subscription_id=subscription_id,
        resource_group=resource_group,
        pg_password=pg_password,
        location=cloud_context.region or "eastus",
    )

    deployer = AzureDeployer(config)
    state = deployer.deploy()
    logger.info("Azure auto-provision complete. Service URL: %s", state.server_url)
    return True
