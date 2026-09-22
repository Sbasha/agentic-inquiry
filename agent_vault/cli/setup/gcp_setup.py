"""GCP (CloudSQL) setup handler for Agent-Vault.

Provides setup for Cloud SQL PostgreSQL environments with IAM authentication
and automatic Cloud SQL Proxy management.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from agent_vault.cli.setup.base import (
    SetupError,
    run_async,
    print_success,
    print_info,
    print_error,
    print_warning,
    prompt_input,
    prompt_choice,
    prompt_confirm,
)
from agent_vault.cli.setup.gcp_base import GCPBaseSetup
from agent_vault.cli.setup.templates import CLOUDSQL_TEMPLATE, render_template
from agent_vault.cli.setup.gcp_utils import (
    list_cloudsql_instances,
    list_databases,
    check_database_exists,
    create_database,
    CloudSQLInstance,
)
from agent_vault.cli.setup.validators import (
    validate_cloudsql_connection,
    check_pgvector_extension,
)

logger = logging.getLogger(__name__)


class GCPSetup(GCPBaseSetup):
    """Setup handler for Cloud SQL (GCP) environments.

    Creates a Cloud SQL-backed environment with:
    - Cloud SQL Connector for secure connections
    - IAM authentication (ADC-based)
    - Automatic Cloud SQL Proxy management
    - pgvector extension for vector storage

    Example:
        >>> setup = GCPSetup(env_name="gcp-prod")
        >>> setup.run()
        True
    """

    backend_type = "cloudsql"

    def __init__(
        self,
        env_name: Optional[str] = None,
        is_dev: bool = False,
        workspace: Optional[Path] = None,
        project: Optional[str] = None,
        region: Optional[str] = None,
        instance: Optional[str] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        table_prefix: Optional[str] = None,
    ) -> None:
        """Initialize GCP setup.

        Args:
            env_name: Environment name (e.g., "gcp-prod", "gcp-staging")
            is_dev: If True, creates a test environment (no auto-start proxy)
            workspace: Workspace root path
            project: GCP project ID (auto-detected if None)
            region: GCP region (prompts if None)
            instance: Cloud SQL instance name (prompts if None)
            database: Database name (default: agent-vault)
            user: IAM user email (auto-detected if None)
            table_prefix: Table prefix for isolation (default: agv_)
        """
        super().__init__(
            env_name=env_name,
            is_dev=is_dev,
            workspace=workspace,
            project=project,
            database=database,
            user=user,
            table_prefix=table_prefix,
        )
        self._region = region
        self._instance = instance

    def run(self) -> bool:
        """Run the GCP setup wizard.

        Returns:
            True if setup completed successfully
        """
        print("========================================")
        print("  Cloud SQL (GCP) Environment Setup")
        print("========================================")

        try:
            if not self.check_gcloud():
                return False

            if not self.check_auth():
                return False

            project = self.get_project()
            if not project:
                return False

            instance, region = self._select_instance(project)
            if not instance or not region:
                return False

            database = self._get_database_with_creation(project, instance)
            if not database:
                return False

            user = self.get_user(project)
            if not user:
                return False

            all_preset = bool(
                self._project and self._instance and self._region
                and self._database and self._user
            )
            table_prefix = self.get_table_prefix(all_preset)

            print_info("Validating Cloud SQL connection...")
            success = run_async(
                self._validate_connection(project, region, instance, database, user)
            )
            if not success:
                return False

            name = self.env_name
            print_info(f"Environment name: {name}")

            if self.config_path.exists():
                print_error(f"Environment '{name}' already exists at {self.config_path}")
                print_info("Use a different name or delete the existing environment first.")
                return False

            print_info("Creating environment directory...")
            self.create_env_directory()

            print_info("Writing configuration...")
            auto_start = not self.is_dev

            config = render_template(
                CLOUDSQL_TEMPLATE,
                {
                    "ENV_NAME": name,
                    "root": str(self.env_dir),
                    "GCP_PROJECT": project,
                    "GCP_REGION": region,
                    "GCP_INSTANCE": instance,
                    "GCP_DATABASE": database,
                    "GCP_USER": user,
                    "TABLE_PREFIX": table_prefix,
                },
            )

            config["services"]["auto_start_proxy"] = auto_start
            self.write_config(config)

            print_info("Registering environment...")
            self.register_environment(metadata={
                "setup_type": "gcp",
                "backend": "cloudsql",
                "project": project,
                "region": region,
                "instance": instance,
                "database": database,
                "table_prefix": table_prefix,
                "auto_start_proxy": auto_start,
            })

            self.set_active()

            print_success(f"Environment '{name}' created successfully!")
            print("\nConfiguration:")
            print(f"  Project: {project}")
            print(f"  Region: {region}")
            print(f"  Instance: {instance}")
            print(f"  Database: {database}")
            print(f"  User: {user}")
            print(f"  Auto-start proxy: {auto_start}")

            print("\nNext steps:")
            print("  1. Index your codebase: agv index .")
            print("  2. Start the server: agv serve")
            print("  3. Search: agv search 'your query'")

            if not auto_start:
                print_warning(
                    "\nProxy auto-start is disabled for test environments. "
                    "Start manually if needed: agv proxy start"
                )

            print(f"\nConfiguration: {self.config_path}")
            return True

        except SetupError as e:
            print_error(str(e))
            self.cleanup_partial()
            return False
        except Exception as e:
            print_error(f"Unexpected error: {e}")
            logger.exception("GCP setup failed")
            self.cleanup_partial()
            return False

    def _select_instance(self, project: str) -> tuple[Optional[str], Optional[str]]:
        """Select or specify Cloud SQL instance.

        Args:
            project: GCP project ID

        Returns:
            Tuple of (instance_name, region) or (None, None)
        """
        if self._instance and self._region:
            return self._instance, self._region

        print_info("Fetching Cloud SQL instances...")
        instances = list_cloudsql_instances(project)

        if not instances:
            print_warning("No PostgreSQL Cloud SQL instances found")
            print_info("You can create one in the GCP Console:")
            print_info(f"  https://console.cloud.google.com/sql/instances?project={project}")

            if prompt_confirm("Enter instance details manually?"):
                instance = prompt_input("Instance name", required=True)
                region = prompt_input("Region (e.g., us-central1)", required=True)
                return instance, region
            return None, None

        print_info(f"Found {len(instances)} PostgreSQL instance(s)")

        runnable = [i for i in instances if i.state == "RUNNABLE"]

        if not runnable:
            print_warning("No running instances found")
            options = [i.display_name for i in instances]
            options.append("Enter manually")
        else:
            options = [i.display_name for i in runnable]
            options.append("Enter manually")

        choice = prompt_choice("Select Cloud SQL instance:", options)

        if choice == "Enter manually":
            instance = prompt_input("Instance name", required=True)
            region = prompt_input("Region (e.g., us-central1)", required=True)
            return instance, region

        for inst in instances:
            if inst.display_name == choice:
                return inst.name, inst.region

        return None, None

    def _get_database_with_creation(self, project: str, instance: str) -> Optional[str]:
        """Get or create database via gcloud.

        Args:
            project: GCP project ID
            instance: Cloud SQL instance name

        Returns:
            Database name or None
        """
        if self._database:
            database = self._database
        else:
            databases = list_databases(project, instance)

            if databases:
                print_info(f"Existing databases: {', '.join(databases)}")

            database = prompt_input(
                "Database name",
                default="agent-vault",
            )

        exists = check_database_exists(project, instance, database)

        if not exists:
            print_warning(f"Database '{database}' does not exist")

            if prompt_confirm("Create the database now?"):
                success, message = create_database(project, instance, database)
                if success:
                    print_success(message)
                else:
                    print_error(message)
                    return None
            else:
                print_warning(
                    "Database must exist before proceeding. "
                    "Create it manually or let setup create it."
                )
                return None
        else:
            print_success(f"Database '{database}' exists")

        return database

    async def _validate_connection(
        self,
        project: str,
        region: str,
        instance: str,
        database: str,
        user: str,
    ) -> bool:
        """Validate Cloud SQL connection.

        Args:
            project: GCP project ID
            region: GCP region
            instance: Cloud SQL instance name
            database: Database name
            user: IAM user email

        Returns:
            True if connection is successful
        """
        success, message = await validate_cloudsql_connection(
            project=project,
            region=region,
            instance=instance,
            database=database,
            user=user,
        )

        if success:
            print_success(message)
            return True

        print_error(message)

        if "Permission denied" in message:
            print_info("Suggestions:")
            print_info(f"  - Grant IAM database access: gcloud sql users create {user}")
            print_info("  - Ensure roles/cloudsql.instanceUser role is granted")
        elif "ADC not configured" in message:
            print_info("Run: gcloud auth application-default login")
        elif "Instance not found" in message:
            print_info(f"  - Verify instance exists: gcloud sql instances list --project={project}")

        return False
