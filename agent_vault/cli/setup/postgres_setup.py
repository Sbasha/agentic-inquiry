"""PostgreSQL setup handler for Agent-Vault.

Provides setup for PostgreSQL environments with direct connection strings.
"""

from __future__ import annotations

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
    prompt_confirm,
)
from agent_vault.cli.setup.templates import POSTGRES_TEMPLATE, render_template
from agent_vault.cli.setup.validators import (
    validate_postgres_connection,
    validate_connection_string_format,
    check_pgvector_extension,
    create_pgvector_extension,
)

logger = logging.getLogger(__name__)


class PostgresSetup(BaseSetup):
    """Setup handler for PostgreSQL environments.

    Creates a PostgreSQL-backed environment with:
    - Direct PostgreSQL connection (connection string)
    - pgvector extension for vector storage
    - PostgreSQL for all storage roles (vector, graph, events, file tracker)

    Example:
        >>> setup = PostgresSetup(env_name="prod")
        >>> setup.run()
        True
    """

    backend_type = "postgresql"

    def __init__(
        self,
        env_name: Optional[str] = None,
        is_dev: bool = False,
        workspace: Optional[Path] = None,
        connection_string: Optional[str] = None,
        table_prefix: Optional[str] = None,
    ) -> None:
        """Initialize PostgreSQL setup.

        Args:
            env_name: Environment name (e.g., "prod", "staging")
            is_dev: If True, creates a test environment
            workspace: Workspace root path
            connection_string: PostgreSQL connection string (prompts if None)
            table_prefix: Table prefix for isolation (default: agv_)
        """
        super().__init__(env_name=env_name, is_dev=is_dev, workspace=workspace)
        self._connection_string = connection_string
        self._table_prefix = table_prefix or "agv_"

    def run(self) -> bool:
        """Run the PostgreSQL setup wizard.

        Steps:
        1. Confirm environment name
        2. Get connection string
        3. Validate connection
        4. Check/create pgvector extension
        5. Write config.yaml
        6. Register environment

        Returns:
            True if setup completed successfully
        """
        print("========================================")
        print("  PostgreSQL Environment Setup")
        print("========================================")

        try:
            # Step 1: Get environment name
            name = self.env_name
            print_info(f"Environment name: {name}")

            # Check if environment already exists
            if self.config_path.exists():
                print_error(f"Environment '{name}' already exists at {self.config_path}")
                print_info("Use a different name or delete the existing environment first.")
                return False

            # Step 2: Get connection string
            connection_string = self._get_connection_string()
            if not connection_string:
                return False

            # Step 3: Get table prefix (use preset if available)
            if self._connection_string:
                # If connection string was preset, use preset table prefix too
                table_prefix = self._table_prefix
            else:
                table_prefix = prompt_input(
                    "Table prefix (for schema isolation)",
                    default=self._table_prefix,
                )

            # Step 4: Validate connection
            print_info("Validating connection...")
            success = run_async(self._validate_connection(connection_string))
            if not success:
                return False

            # Step 5: Check pgvector
            print_info("Checking pgvector extension...")
            run_async(self._ensure_pgvector(connection_string))

            # Step 6: Create environment directory
            print_info("Creating environment directory...")
            self.create_env_directory()

            # Step 7: Render and write config
            print_info("Writing configuration...")
            config = render_template(
                POSTGRES_TEMPLATE,
                {
                    "ENV_NAME": name,
                    "root": str(self.env_dir),
                    "CONNECTION_STRING": connection_string,
                    "TABLE_PREFIX": table_prefix,
                },
            )
            self.write_config(config)

            # Step 8: Register environment
            print_info("Registering environment...")
            self.register_environment(metadata={
                "setup_type": "postgres",
                "backend": "postgresql",
                "table_prefix": table_prefix,
            })

            # Step 9: Set as active
            self.set_active()

            # Print success
            print_success(f"Environment '{name}' created successfully!")
            print("\nNext steps:")
            print(f"  1. Index your codebase: agv index .")
            print(f"  2. Start the server: agv serve")
            print(f"  3. Search: agv search 'your query'")
            print(f"\nConfiguration: {self.config_path}")

            return True

        except SetupError as e:
            print_error(str(e))
            self.cleanup_partial()
            return False
        except Exception as e:
            print_error(f"Unexpected error: {e}")
            logger.exception("PostgreSQL setup failed")
            self.cleanup_partial()
            return False

    def _get_connection_string(self) -> Optional[str]:
        """Get and validate connection string format.

        Returns:
            Valid connection string or None
        """
        if self._connection_string:
            conn_str = self._connection_string
        else:
            print("\nEnter your PostgreSQL connection string.")
            print("Format: postgresql://user:password@host:port/database")
            print("Example: postgresql://myuser:mypass@localhost:5432/agent-vault")
            conn_str = prompt_input(
                "Connection string",
                default="postgresql://localhost:5432/agent-vault",
            )

        # Validate format
        valid, error = validate_connection_string_format(conn_str)
        if not valid:
            print_error(f"Invalid connection string: {error}")
            return None

        return conn_str

    async def _validate_connection(self, connection_string: str) -> bool:
        """Validate PostgreSQL connection.

        Args:
            connection_string: Connection string to validate

        Returns:
            True if connection is successful
        """
        success, message = await validate_postgres_connection(connection_string)

        if success:
            print_success(message)
            return True
        else:
            print_error(message)

            # Provide helpful suggestions
            if "Connection refused" in message:
                print_info("Suggestions:")
                print_info("  - Check if PostgreSQL is running")
                print_info("  - Verify the host and port are correct")
                print_info("  - Check firewall settings")
            elif "Invalid password" in message:
                print_info("Suggestions:")
                print_info("  - Check the password in your connection string")
                print_info("  - Verify the user exists in PostgreSQL")
            elif "Database not found" in message:
                print_info("Suggestions:")
                print_info("  - Create the database: createdb agent-vault")
                print_info("  - Or specify an existing database name")

            return False

    async def _ensure_pgvector(self, connection_string: str) -> None:
        """Check and optionally create pgvector extension.

        Args:
            connection_string: Connection string
        """
        has_pgvector = await check_pgvector_extension(connection_string)

        if has_pgvector:
            print_success("pgvector extension is installed")
            return

        print_warning("pgvector extension is not installed")

        if prompt_confirm("Would you like to create the pgvector extension?"):
            success, message = await create_pgvector_extension(connection_string)
            if success:
                print_success(message)
            else:
                print_warning(message)
                print_info("You may need to create it manually as a superuser:")
                print_info("  CREATE EXTENSION vector;")
        else:
            print_warning(
                "pgvector is required for vector search. "
                "Please create it manually before indexing."
            )
