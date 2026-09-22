"""Shared GCP setup logic for CloudSQL and AlloyDB handlers.

Provides common GCP authentication, project selection, and user detection
used by both GCPSetup (CloudSQL) and AlloyDBSetup.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from agent_vault.cli.setup.base import (
    BaseSetup,
    print_success,
    print_info,
    print_error,
    print_warning,
    prompt_input,
    prompt_confirm,
)
from agent_vault.cli.setup.gcp_utils import (
    check_gcloud_installed,
    check_gcloud_auth,
    check_adc_configured,
    get_current_project,
    get_iam_email,
)

logger = logging.getLogger(__name__)


class GCPBaseSetup(BaseSetup):
    """Base class for GCP-backed setup handlers.

    Provides shared GCP authentication, project selection, and user
    detection logic used by both CloudSQL and AlloyDB setup wizards.

    Subclasses must still implement ``run()`` and set ``backend_type``.
    """

    def __init__(
        self,
        env_name: Optional[str] = None,
        is_dev: bool = False,
        workspace: Optional[Path] = None,
        project: Optional[str] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        table_prefix: Optional[str] = None,
    ) -> None:
        """Initialize GCP base setup.

        Args:
            env_name: Environment name
            is_dev: If True, creates a test environment
            workspace: Workspace root path
            project: GCP project ID (auto-detected if None)
            database: Database name (default: agent-vault)
            user: IAM user email (auto-detected if None)
            table_prefix: Table prefix for isolation (default: agv_)
        """
        super().__init__(env_name=env_name, is_dev=is_dev, workspace=workspace)
        self._project = project
        self._database = database  # None means prompt user
        self._user = user
        self._table_prefix = table_prefix or "agv_"

    def check_gcloud(self) -> bool:
        """Check if gcloud CLI is installed.

        Returns:
            True if gcloud is available
        """
        if check_gcloud_installed():
            print_success("gcloud CLI found")
            return True

        print_error("gcloud CLI not found")
        print_info("Please install the Google Cloud SDK:")
        print_info("  https://cloud.google.com/sdk/docs/install")
        return False

    def check_auth(self) -> bool:
        """Check GCP authentication and ADC.

        Returns:
            True if authenticated with valid ADC
        """
        auth_info = check_gcloud_auth()
        if not auth_info:
            print_error("Not logged in to gcloud")
            print_info("Please run: gcloud auth login")
            return False

        print_success(f"Logged in as: {auth_info.account}")

        adc_ok, adc_msg = check_adc_configured()
        if not adc_ok:
            print_warning("Application Default Credentials not configured")
            print_info(adc_msg)

            if prompt_confirm("Would you like to configure ADC now?"):
                import subprocess

                result = subprocess.run(
                    ["gcloud", "auth", "application-default", "login"],
                    timeout=120,
                )
                if result.returncode != 0:
                    print_error("ADC configuration failed")
                    return False
                print_success("ADC configured")
            else:
                print_error("ADC is required for GCP database connections")
                return False
        else:
            print_success("ADC configured")

        return True

    def get_project(self) -> Optional[str]:
        """Get GCP project ID.

        Returns:
            Project ID or None
        """
        if self._project:
            project = self._project
        else:
            current_project = get_current_project()

            if current_project:
                print_info(f"Current GCP project: {current_project}")
                if prompt_confirm("Use this project?"):
                    project = current_project
                else:
                    project = prompt_input("GCP project ID", required=True)
            else:
                project = prompt_input("GCP project ID", required=True)

        if not project:
            print_error("Project ID is required")
            return None

        print_success(f"Using project: {project}")
        return project

    def get_database(self) -> Optional[str]:
        """Get database name.

        Returns:
            Database name or None
        """
        if self._database:
            return self._database

        return prompt_input("Database name", default="agent-vault")

    def get_user(self, project: str) -> Optional[str]:
        """Get IAM user email.

        Args:
            project: GCP project ID

        Returns:
            IAM user email or None
        """
        if self._user:
            return self._user

        detected_user = get_iam_email(project)

        if detected_user:
            print_info(f"Detected IAM user: {detected_user}")
            if prompt_confirm("Use this user?"):
                return detected_user

        return prompt_input(
            "IAM database user (email)",
            default=detected_user,
            required=True,
        )

    def get_table_prefix(self, all_preset: bool) -> str:
        """Get table prefix for schema isolation.

        Args:
            all_preset: If True, skip prompt and use preset value

        Returns:
            Table prefix string
        """
        if all_preset:
            return self._table_prefix

        return prompt_input(
            "Table prefix (for schema isolation)",
            default=self._table_prefix,
        )
