"""AWS deploy orchestrator for Agent-Vault.

Wraps ``scripts/deploy/aws-deploy.sh`` to provision an RDS for
PostgreSQL instance + ECR repository + App Runner service. The script
is the supported deployment path; the manual equivalent (CLI snippets,
config-file shape, troubleshooting) is documented end-to-end in
``docs/backends/rds.md``. If you're operating without the script —
restricted IAM, multi-account topology, IaC migration — that doc has
the manual recipe.
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

logger = logging.getLogger("agv.deploy.aws")

_AWS_SCRIPT_REL = "scripts/deploy/aws-deploy.sh"


@dataclass
class AWSDeployConfig:
    """Configuration for a Agent-Vault AWS deployment.

    Attributes:
        aws_account_id: AWS account ID (required)
        rds_password: RDS postgres user password (required)
        region: AWS region (default: us-east-1)
        rds_instance_id: RDS instance identifier
        rds_instance_class: RDS instance class
        ecr_repo: ECR repository name
        service_name: App Runner service name
        image_tag: Container image tag
        iam_role_name: IAM role for App Runner
        db_name: Database name
        db_user: Database user
    """

    aws_account_id: str
    rds_password: str
    region: str = "us-east-1"
    rds_instance_id: str = "agv-postgres"
    rds_instance_class: str = "db.t3.micro"
    ecr_repo: str = "agent-vault"
    service_name: str = "agent-vault"
    image_tag: str = "latest"
    iam_role_name: str = "agv-app-runner-role"
    db_name: str = "agent-vault"
    db_user: str = "postgres"
    extra_env: dict[str, str] = field(default_factory=dict)


class AWSDeployer:
    """Orchestrates Agent-Vault deployment to AWS.

    Delegates to ``scripts/deploy/aws-deploy.sh`` via ``run_shell_script()``,
    tracking progress in a ``DeployState`` resume file.

    Steps:
        1. check_prerequisites   — aws CLI + docker + credentials
        2. create_rds            — RDS PostgreSQL instance
        3. configure_iam         — IAM role + SSM secret
        4. build_container       — Docker build + push to ECR
        5. deploy_app_runner     — App Runner service create/update
        6. smoke_test            — poll /api/v1/health until 200

    Example::

        config = AWSDeployConfig(
            aws_account_id="123456789012",
            rds_password="s3cr3t",
        )
        deployer = AWSDeployer(config)
        state = deployer.deploy()
        print(f"Deployed to: {state.server_url}")
    """

    def __init__(
        self,
        config: AWSDeployConfig,
        deploy_dir: Optional[str] = None,
        script_path: Optional[str] = None,
    ) -> None:
        """Initialise the deployer.

        Args:
            config: AWS deployment configuration.
            deploy_dir: Directory for state files (default: ``.agv/deploy``).
            script_path: Explicit path to ``aws-deploy.sh``.
        """
        self._config = config
        self._deploy_dir = Path(deploy_dir or DEPLOY_DIR)
        self._script_path = script_path or str(Path.cwd() / _AWS_SCRIPT_REL)

    def deploy(self) -> DeployState:
        """Run the full AWS deployment.

        Returns:
            Completed ``DeployState`` with ``server_url`` populated.

        Raises:
            RuntimeError: If any deploy step fails.
        """
        state = self._load_or_create_state()
        api_key = state.api_key or generate_api_key()
        state.api_key = api_key

        env = self._build_env(api_key)
        logger.info("Starting AWS deploy for account=%s", self._config.aws_account_id)

        result = run_shell_script(self._script_path, env=env)

        if result.returncode != 0:
            logger.error("AWS deploy script failed:\n%s", result.stderr)
            raise RuntimeError(
                f"AWS deploy script exited with code {result.returncode}.\n"
                f"stderr:\n{result.stderr}"
            )

        logger.info("AWS deploy script output:\n%s", result.stdout)

        url_file = self._deploy_dir / "service-url.txt"
        server_url: Optional[str] = url_file.read_text().strip() if url_file.exists() else None

        step_names = [
            ("check_prerequisites", "Check prerequisites"),
            ("create_rds", "Create RDS PostgreSQL instance"),
            ("configure_iam", "Configure IAM role and SSM secret"),
            ("build_container", "Build and push container to ECR"),
            ("deploy_app_runner", "Deploy to App Runner"),
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
        state.save(self._deploy_dir / "aws-state.json")
        logger.info("AWS deploy complete. Service URL: %s", server_url)
        return state

    def _load_or_create_state(self) -> DeployState:
        state_path = self._deploy_dir / "aws-state.json"
        state = DeployState.load(state_path)
        if state is None:
            state = DeployState(
                provider="aws",
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                steps=[],
                api_key="",
                server_url=None,
            )
        return state

    def _build_env(self, api_key: str) -> dict[str, str]:
        env: dict[str, str] = {
            "agv_AWS_ACCOUNT_ID": self._config.aws_account_id,
            "agv_AWS_REGION": self._config.region,
            "agv_RDS_INSTANCE_ID": self._config.rds_instance_id,
            "agv_RDS_INSTANCE_CLASS": self._config.rds_instance_class,
            "agv_RDS_PASSWORD": self._config.rds_password,
            "agv_ECR_REPO": self._config.ecr_repo,
            "agv_SERVICE_NAME": self._config.service_name,
            "agv_IMAGE_TAG": self._config.image_tag,
            "agv_IAM_ROLE_NAME": self._config.iam_role_name,
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
