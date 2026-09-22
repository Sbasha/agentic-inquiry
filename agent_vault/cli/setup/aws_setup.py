"""AWS RDS setup handler for Agent-Vault.

Provides setup for AWS RDS PostgreSQL environments with IAM authentication
or standard password authentication.
"""

from __future__ import annotations

import getpass
import logging
from pathlib import Path
from typing import Optional

from agent_vault.cli.setup.base import (
    BaseSetup,
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
from agent_vault.cli.setup.templates import RDS_TEMPLATE, render_template
from agent_vault.cli.setup.aws_utils import (
    check_aws_cli_installed,
    check_aws_auth,
    get_current_region,
    list_rds_instances,
    check_iam_auth_enabled,
    RDSInstance,
)

logger = logging.getLogger(__name__)


class AWSSetup(BaseSetup):
    """Setup handler for AWS RDS environments.

    Creates an RDS-backed environment with:
    - Direct SSL connection to RDS
    - IAM token authentication (optional) or standard password authentication
    - pgvector extension for vector storage

    Example:
        >>> setup = AWSSetup(env_name="aws-prod")
        >>> setup.run()
        True
    """

    backend_type = "rds"

    def __init__(
        self,
        env_name: Optional[str] = None,
        is_dev: bool = False,
        workspace: Optional[Path] = None,
        region: Optional[str] = None,
        instance: Optional[str] = None,
        host: Optional[str] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        use_iam_auth: bool = False,
        table_prefix: Optional[str] = None,
    ) -> None:
        """Initialize AWS RDS setup.

        Args:
            env_name: Environment name (e.g., "aws-prod", "aws-staging")
            is_dev: If True, creates a test environment
            workspace: Workspace root path
            region: AWS region (e.g., "us-east-1"; auto-detected if None)
            instance: RDS instance identifier (prompts if None)
            host: RDS endpoint hostname (auto-discovered if None)
            database: Database name (default: agent-vault)
            user: Database username (prompts if None)
            password: Database password (prompts if None and use_iam_auth is False)
            use_iam_auth: Use AWS IAM token authentication instead of password
            table_prefix: Table prefix for isolation (default: agv_)
        """
        super().__init__(env_name=env_name, is_dev=is_dev, workspace=workspace)
        self._region = region
        self._instance = instance
        self._host = host
        self._database = database
        self._user = user
        self._password = password
        self._use_iam_auth = use_iam_auth
        self._table_prefix = table_prefix or "agv_"

    # ------------------------------------------------------------------
    # Public run() method
    # ------------------------------------------------------------------

    def run(self) -> bool:
        """Run the AWS RDS setup wizard.

        Returns:
            True if setup completed successfully
        """
        print("========================================")
        print("  AWS RDS Environment Setup")
        print("========================================")

        try:
            if not self._check_aws_cli():
                return False

            if not self._check_auth():
                return False

            region = self._get_region()
            if not region:
                return False

            instance_obj = self._select_instance(region)
            if instance_obj is None:
                return False

            instance = instance_obj.identifier
            host = instance_obj.endpoint_host
            port = instance_obj.endpoint_port

            database = self._get_database(instance_obj)
            if not database:
                return False

            use_iam_auth, user, password = self._get_credentials(
                region, instance, host, port
            )
            if user is None:
                return False

            all_preset = bool(
                self._region and self._instance and self._host
                and self._database and self._user
                and (self._password or self._use_iam_auth)
            )
            table_prefix = self._get_table_prefix(all_preset)

            print_info("Validating RDS connection...")
            success = run_async(
                self._validate_connection(
                    host=host,
                    port=port,
                    database=database,
                    user=user,
                    password=password,
                    use_iam_auth=use_iam_auth,
                    region=region,
                    instance=instance,
                )
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
            config = render_template(
                RDS_TEMPLATE,
                {
                    "ENV_NAME": name,
                    "root": str(self.env_dir),
                    "AWS_REGION": region,
                    "RDS_INSTANCE": instance,
                    "RDS_HOST": host,
                    "RDS_DATABASE": database,
                    "RDS_USER": user,
                    "TABLE_PREFIX": table_prefix,
                },
            )

            # Inject runtime-determined values as the correct Python types
            rds_backend = config["storage"]["backends"]["rds"]
            rds_backend["port"] = port
            if use_iam_auth:
                rds_backend["use_iam_auth"] = True
            elif password:
                rds_backend["password"] = password

            self.write_config(config)

            print_info("Registering environment...")
            self.register_environment(metadata={
                "setup_type": "aws",
                "backend": "rds",
                "region": region,
                "instance": instance,
                "host": host,
                "database": database,
                "table_prefix": table_prefix,
                "use_iam_auth": use_iam_auth,
            })

            self.set_active()

            print_success(f"Environment '{name}' created successfully!")
            print("\nConfiguration:")
            print(f"  Region:    {region}")
            print(f"  Instance:  {instance}")
            print(f"  Host:      {host}:{port}")
            print(f"  Database:  {database}")
            print(f"  User:      {user}")
            print(f"  Auth:      {'IAM token' if use_iam_auth else 'password'}")
            print(f"  SSL:       required")

            print("\nNext steps:")
            print("  1. Index your codebase: agv index .")
            print("  2. Start the server: agv serve")
            print("  3. Search: agv search 'your query'")

            print(f"\nConfiguration: {self.config_path}")
            return True

        except SetupError as e:
            print_error(str(e))
            self.cleanup_partial()
            return False
        except Exception as e:
            print_error(f"Unexpected error: {e}")
            logger.exception("AWS RDS setup failed")
            self.cleanup_partial()
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_aws_cli(self) -> bool:
        """Check if the AWS CLI is installed."""
        if check_aws_cli_installed():
            print_success("AWS CLI found")
            return True

        print_error("AWS CLI not found")
        print_info("Please install the AWS CLI:")
        print_info("  https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html")
        return False

    def _check_auth(self) -> bool:
        """Check AWS authentication."""
        auth_info = check_aws_auth()
        if not auth_info:
            print_error("Not authenticated with AWS")
            print_info("Please run: aws configure  (or set AWS_ACCESS_KEY_ID / AWS_PROFILE)")
            return False

        print_success(f"Authenticated as: {auth_info.display_name}")
        print_info(f"  Account: {auth_info.account_id}")
        return True

    def _get_region(self) -> Optional[str]:
        """Get the AWS region to use."""
        if self._region:
            print_success(f"Using region: {self._region}")
            return self._region

        current = get_current_region()
        if current:
            print_info(f"Detected AWS region: {current}")
            if prompt_confirm("Use this region?"):
                return current

        region = prompt_input(
            "AWS region (e.g., us-east-1)",
            default=current,
            required=True,
        )
        return region if region else None

    def _select_instance(self, region: str) -> Optional[RDSInstance]:
        """Select or specify an RDS instance.

        Args:
            region: AWS region to query

        Returns:
            Selected RDSInstance, or None
        """
        if self._instance and self._host:
            # Build a synthetic RDSInstance from the preset values
            return RDSInstance(
                identifier=self._instance,
                engine="postgres",
                engine_version="",
                status="available",
                endpoint_host=self._host,
                endpoint_port=self._port_from_config(),
                region=region,
                db_name=self._database,
            )

        print_info("Fetching RDS instances...")
        instances = list_rds_instances(region)

        if not instances:
            print_warning("No PostgreSQL RDS instances found in this region")
            print_info("You can create one in the AWS console:")
            print_info(f"  https://{region}.console.aws.amazon.com/rds/home?region={region}")

            if prompt_confirm("Enter instance details manually?"):
                return self._prompt_instance_manually(region)
            return None

        available = [i for i in instances if i.status == "available"]

        if not available:
            print_warning("No 'available' instances found (all may be stopping/starting)")
            options = [i.display_name for i in instances]
            options.append("Enter manually")
        else:
            print_info(f"Found {len(available)} available PostgreSQL instance(s)")
            options = [i.display_name for i in available]
            options.append("Enter manually")

        choice = prompt_choice("Select RDS instance:", options)

        if choice == "Enter manually":
            return self._prompt_instance_manually(region)

        for inst in instances:
            if inst.display_name == choice:
                return inst

        return None

    def _prompt_instance_manually(self, region: str) -> Optional[RDSInstance]:
        """Prompt for RDS instance details manually."""
        identifier = prompt_input("RDS instance identifier", required=True)
        host = prompt_input("RDS endpoint hostname", required=True)
        port_str = prompt_input("Port", default="5432")
        try:
            port = int(port_str) if port_str else 5432
        except ValueError:
            port = 5432

        return RDSInstance(
            identifier=identifier,
            engine="postgres",
            engine_version="",
            status="available",
            endpoint_host=host,
            endpoint_port=port,
            region=region,
            db_name=None,
        )

    def _port_from_config(self) -> int:
        """Return the preset port, defaulting to 5432."""
        return 5432

    def _get_database(self, instance: RDSInstance) -> Optional[str]:
        """Get the database name to use."""
        if self._database:
            return self._database

        default = instance.db_name or "agent-vault"
        return prompt_input("Database name", default=default)

    def _get_credentials(
        self,
        region: str,
        instance_id: str,
        host: str,
        port: int,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """Determine auth method and collect credentials.

        Returns:
            Tuple of (use_iam_auth, username, password_or_None)
        """
        # If everything was preset, honour it
        if self._user and (self._password or self._use_iam_auth):
            return self._use_iam_auth, self._user, self._password

        # Detect if IAM auth is available on the instance
        iam_available = check_iam_auth_enabled(instance_id, region)

        # Determine auth mode
        if self._use_iam_auth:
            use_iam = True
        elif iam_available:
            print_info("IAM database authentication is enabled on this instance.")
            use_iam = prompt_confirm("Use AWS IAM token authentication?", default=True)
        else:
            use_iam = False

        # Get username
        user = self._user or prompt_input("Database username", required=True)

        # Get password if not using IAM auth
        password: Optional[str] = None
        if not use_iam:
            password = self._password
            if not password:
                try:
                    password = getpass.getpass(f"Password for '{user}': ")
                    if not password:
                        print_error("Password is required when not using IAM authentication")
                        return False, None, None
                except (KeyboardInterrupt, EOFError):
                    print("\nSetup cancelled.")
                    return False, None, None

        return use_iam, user, password

    def _get_table_prefix(self, all_preset: bool) -> str:
        """Get the table prefix for schema isolation."""
        if all_preset:
            return self._table_prefix

        return prompt_input(
            "Table prefix (for schema isolation)",
            default=self._table_prefix,
        )

    async def _validate_connection(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: Optional[str],
        use_iam_auth: bool,
        region: str,
        instance: str,
    ) -> bool:
        """Validate RDS connection.

        Args:
            host: RDS endpoint hostname
            port: Port number
            database: Database name
            user: Database username
            password: Password (None when using IAM auth)
            use_iam_auth: Whether to use IAM token authentication
            region: AWS region
            instance: RDS instance identifier

        Returns:
            True if connection is successful
        """
        from agent_vault.cli.setup.validators import validate_rds_connection

        success, message = await validate_rds_connection(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            use_iam_auth=use_iam_auth,
            region=region,
            instance=instance,
        )

        if success:
            print_success(message)
            return True

        print_error(message)

        if "SSL" in message or "ssl" in message:
            print_info("Suggestions:")
            print_info("  - Ensure your RDS instance security group allows inbound connections")
            print_info("  - Check that SSL is enforced on the RDS instance")
        elif "password" in message.lower() or "authentication" in message.lower():
            print_info("Suggestions:")
            print_info(f"  - Verify password for user '{user}'")
            print_info("  - Or use IAM auth: run setup again with --use-iam-auth")
        elif "does not exist" in message.lower() or "not found" in message.lower():
            print_info(f"  - Verify database '{database}' exists on the RDS instance")
        elif "timeout" in message.lower():
            print_info("  - Check VPC / security group rules allow your IP on port 5432")

        if prompt_confirm("Skip connection validation and continue?", default=False):
            print_warning("Skipping validation — verify connectivity before indexing")
            return True

        return False
