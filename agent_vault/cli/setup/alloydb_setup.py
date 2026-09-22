"""AlloyDB setup handler for Agent-Vault.

Provides setup for AlloyDB environments with server-side embeddings
via Vertex AI, IAM authentication, and AlloyDB Auth Proxy management.
"""

from __future__ import annotations

import asyncio
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
from agent_vault.cli.setup.templates import ALLOYDB_TEMPLATE, render_template
from agent_vault.cli.setup.gcp_utils import (
    list_alloydb_clusters,
    list_alloydb_instances,
    AlloyDBCluster,
    AlloyDBInstance,
)

logger = logging.getLogger(__name__)


class AlloyDBSetup(GCPBaseSetup):
    """Setup handler for AlloyDB environments.

    Creates an AlloyDB-backed environment with:
    - Server-side embeddings via Vertex AI (text-embedding-005)
    - IAM authentication (ADC-based)
    - AlloyDB Auth Proxy management
    - google_ml_integration extension for embedding()

    Example:
        >>> setup = AlloyDBSetup(env_name="alloydb-prod")
        >>> setup.run()
        True
    """

    backend_type = "alloydb"

    def __init__(
        self,
        env_name: Optional[str] = None,
        is_dev: bool = False,
        workspace: Optional[Path] = None,
        project: Optional[str] = None,
        region: Optional[str] = None,
        cluster: Optional[str] = None,
        instance: Optional[str] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        table_prefix: Optional[str] = None,
    ) -> None:
        """Initialize AlloyDB setup.

        Args:
            env_name: Environment name (e.g., "alloydb-prod")
            is_dev: If True, creates a test environment
            workspace: Workspace root path
            project: GCP project ID (auto-detected if None)
            region: GCP region (prompts if None)
            cluster: AlloyDB cluster name (prompts if None)
            instance: AlloyDB instance name (prompts if None)
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
        self._cluster = cluster
        self._instance = instance

    def run(self) -> bool:
        """Run the AlloyDB setup wizard.

        Returns:
            True if setup completed successfully
        """
        print("========================================")
        print("  AlloyDB Environment Setup")
        print("  (Server-Side Embeddings via Vertex AI)")
        print("========================================")

        try:
            if not self.check_gcloud():
                return False

            if not self.check_auth():
                return False

            project = self.get_project()
            if not project:
                return False

            cluster, region = self._select_cluster(project)
            if not cluster or not region:
                return False

            instance = self._select_instance(project, region, cluster)
            if not instance:
                return False

            database = self.get_database()
            if not database:
                return False

            user = self.get_user(project)
            if not user:
                return False

            all_preset = bool(
                self._project and self._cluster and self._instance
                and self._region and self._database and self._user
            )
            table_prefix = self.get_table_prefix(all_preset)

            print_info("Validating AlloyDB connection...")
            success = run_async(
                self._validate_connection(project, region, cluster, instance, database, user)
            )
            # If validation fails, we still allow setup to continue as long as it's not a fatal error
            # This helps when the proxy isn't running yet during setup.
            if not success:
                print_warning("Connection validation failed. Ensure your network and IAM settings are correct.")
                if not prompt_confirm("Continue with setup anyway?", default=True):
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
                ALLOYDB_TEMPLATE,
                {
                    "ENV_NAME": name,
                    "root": str(self.env_dir),
                    "GCP_PROJECT": project,
                    "GCP_REGION": region,
                    "ALLOYDB_CLUSTER": cluster,
                    "ALLOYDB_INSTANCE": instance,
                    "GCP_DATABASE": database,
                    "GCP_USER": user,
                    "TABLE_PREFIX": table_prefix,
                },
            )

            config["services"]["auto_start_proxy"] = auto_start
            self.write_config(config)

            print_info("Registering environment...")
            self.register_environment(metadata={
                "setup_type": "alloydb",
                "backend": "alloydb",
                "project": project,
                "region": region,
                "cluster": cluster,
                "instance": instance,
                "database": database,
                "table_prefix": table_prefix,
                "auto_start_proxy": auto_start,
                "embedding_provider": "none",
                "embedding_model": "text-embedding-005",
                "embedding_dimensions": 768,
            })

            self.set_active()

            print_success(f"Environment '{name}' created successfully!")
            print("\nConfiguration:")
            print(f"  Project:    {project}")
            print(f"  Region:     {region}")
            print(f"  Cluster:    {cluster}")
            print(f"  Instance:   {instance}")
            print(f"  Database:   {database}")
            print(f"  User:       {user}")
            print(f"  Embeddings: Server-side (text-embedding-005, 768 dims)")
            print(f"  Proxy:      alloydb-auth-proxy (port 5432)")

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
            logger.exception("AlloyDB setup failed")
            self.cleanup_partial()
            return False

    def _select_cluster(self, project: str) -> tuple[Optional[str], Optional[str]]:
        """Select AlloyDB cluster.

        Returns:
            Tuple of (cluster_name, region) or (None, None)
        """
        if self._cluster and self._region:
            return self._cluster, self._region

        print_info("Fetching AlloyDB clusters...")
        clusters = list_alloydb_clusters(project)

        if not clusters:
            print_warning("No AlloyDB clusters found")
            print_info("Create one with: gcloud alloydb clusters create <name> --region=<region>")
            print_info(f"Or visit: https://console.cloud.google.com/alloydb?project={project}")

            if prompt_confirm("Enter cluster details manually?"):
                cluster = prompt_input("Cluster name", required=True)
                region = prompt_input("Region (e.g., us-central1)", required=True)
                return cluster, region
            return None, None

        ready = [c for c in clusters if c.state == "READY"]

        if not ready:
            print_warning("No READY clusters found")
            options = [c.display_name for c in clusters]
            options.append("Enter manually")
        else:
            print_info(f"Found {len(ready)} ready cluster(s)")
            options = [c.display_name for c in ready]
            options.append("Enter manually")

        choice = prompt_choice("Select AlloyDB cluster:", options)

        if choice == "Enter manually":
            cluster = prompt_input("Cluster name", required=True)
            region = prompt_input("Region (e.g., us-central1)", required=True)
            return cluster, region

        for c in clusters:
            if c.display_name == choice:
                return c.name, c.region

        return None, None

    def _select_instance(self, project: str, region: str, cluster: str) -> Optional[str]:
        """Select AlloyDB instance within a cluster.

        Returns:
            Instance name or None
        """
        if self._instance:
            return self._instance

        print_info(f"Fetching instances for cluster '{cluster}'...")
        instances = list_alloydb_instances(project, region, cluster)

        if not instances:
            print_warning("No instances found in cluster")
            print_info(f"Create one with: gcloud alloydb instances create <name> "
                       f"--cluster={cluster} --region={region} --instance-type=PRIMARY")

            if prompt_confirm("Enter instance name manually?"):
                return prompt_input("Instance name", required=True)
            return None

        ready = [i for i in instances if i.state == "READY"]

        if not ready:
            print_warning("No READY instances found")
            options = [i.display_name for i in instances]
            options.append("Enter manually")
        else:
            print_info(f"Found {len(ready)} ready instance(s)")
            options = [i.display_name for i in ready]
            options.append("Enter manually")

        choice = prompt_choice("Select AlloyDB instance:", options)

        if choice == "Enter manually":
            return prompt_input("Instance name", required=True)

        for i in instances:
            if i.display_name == choice:
                return i.name

        return None

    async def _validate_connection(
        self,
        project: str,
        region: str,
        cluster: str,
        instance: str,
        database: str,
        user: str,
    ) -> bool:
        """Validate AlloyDB connection via Auth Proxy on localhost:5432.

        Falls back to direct IP if proxy isn't running.
        """
        try:
            import asyncpg
        except ImportError:
            print_error("asyncpg is required. Install with: pip install asyncpg")
            return False

        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(
                    host="127.0.0.1",
                    port=5432,
                    user=user,
                    database=database,
                ),
                timeout=10.0,
            )
            try:
                result = await conn.fetchval("SELECT 1")
                if result == 1:
                    print_success("Connected via AlloyDB Auth Proxy (localhost:5432)")
                    return True
                print_error("Unexpected response from database")
                return False
            finally:
                await conn.close()

        except (asyncio.TimeoutError, OSError):
            print_warning("Could not connect via Auth Proxy on localhost:5432")
            print_info("Ensure alloydb-auth-proxy is running:")
            print_info(
                f"  alloydb-auth-proxy "
                f"projects/{project}/locations/{region}/clusters/{cluster}/instances/{instance}"
            )

            if prompt_confirm("Skip connection validation and continue?"):
                print_warning("Skipping validation - verify connectivity before indexing")
                return True
            return False

        except Exception as e:
            error_str = str(e).lower()
            if "permission denied" in error_str or "password" in error_str:
                print_error(f"Authentication failed for user '{user}'")
                print_info("Ensure the user has IAM database access on the AlloyDB instance")
            else:
                print_error(f"Connection failed: {type(e).__name__}")
            return False
