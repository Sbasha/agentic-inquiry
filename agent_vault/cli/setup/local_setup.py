"""Local (LanceDB) setup handler for Agent-Vault.

Provides setup for local development environments using LanceDB as the
vector storage backend and SQLite for metadata.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from agent_vault.cli.setup.base import (
    BaseSetup,
    SetupError,
    print_success,
    print_info,
    print_error,
)
from agent_vault.cli.setup.templates import LANCEDB_TEMPLATE, render_template

logger = logging.getLogger(__name__)


class LocalSetup(BaseSetup):
    """Setup handler for LanceDB (local) environments.

    Creates a local development environment with:
    - LanceDB for vector storage
    - SQLite for metadata (events, file tracker)
    - No external dependencies required

    Example:
        >>> setup = LocalSetup(env_name="dev")
        >>> setup.run()
        True
    """

    backend_type = "lancedb"

    def __init__(
        self,
        env_name: Optional[str] = None,
        is_dev: bool = False,
        workspace: Optional[Path] = None,
    ) -> None:
        """Initialize local setup.

        Args:
            env_name: Environment name (e.g., "dev", "agv")
            is_dev: If True, creates a test environment
            workspace: Workspace root path
        """
        super().__init__(env_name=env_name, is_dev=is_dev, workspace=workspace)

    def run(self) -> bool:
        """Run the local setup wizard.

        Steps:
        1. Confirm environment name
        2. Create environment directory
        3. Create lancedb subdirectory
        4. Write config.yaml with LanceDB template
        5. Register in env-registry.json
        6. Print success message with next steps

        Returns:
            True if setup completed successfully
        """
        print("========================================")
        print("  LanceDB (Local) Environment Setup")
        print("========================================")

        try:
            # Step 1: Get environment name
            name = self.env_name
            print_info(f"Environment name: {name}")

            # Check if environment already exists
            if self.config_path.exists():
                print_error(
                    f"Environment '{name}' already exists at {self.config_path}"
                )
                print_info(
                    "Use a different name or delete the existing environment first."
                )
                return False

            # Step 2: Create environment directory
            print_info("Creating environment directory...")
            self.create_env_directory()

            # Step 3: Create lancedb subdirectory
            lancedb_dir = self.env_dir / "lancedb"
            lancedb_dir.mkdir(parents=True, exist_ok=True)
            print_info(f"Created LanceDB directory: {lancedb_dir}")

            # Step 4: Render and write config
            print_info("Writing configuration...")
            config = render_template(
                LANCEDB_TEMPLATE,
                {
                    "ENV_NAME": name,
                    "root": str(self.env_dir),
                },
            )
            self.write_config(config)

            env_file = self.env_dir / ".env"
            env_file.write_text(
                "# Agent-Vault environment overrides for this backend.\n"
                "# Uncomment the next line if indexing aborts on Apple Metal/MPS:\n"
                "# AGV_EMBEDDING_DEVICE=cpu\n",
                encoding="utf-8",
            )
            print_info(f"Wrote environment file: {env_file}")

            # Step 5: Register environment
            print_info("Registering environment...")
            self.register_environment(
                metadata={
                    "setup_type": "local",
                    "backend": "lancedb",
                }
            )

            # Step 6: Set as active
            self.set_active()

            # Print success
            print_success(f"Environment '{name}' created successfully!")
            print("\nNext steps:")
            print("  1. Index your codebase: agv index .")
            print("  2. Start the server: agv serve")
            print("  3. Search: agv search 'your query'")
            print(f"\nConfiguration: {self.config_path}")
            print(
                "If indexing dies on Metal/MPS, uncomment AGV_EMBEDDING_DEVICE=cpu "
                f"in {self.env_dir / '.env'}"
            )

            return True

        except SetupError as e:
            print_error(str(e))
            self.cleanup_partial()
            return False
        except Exception as e:
            print_error(f"Unexpected error: {e}")
            logger.exception("Local setup failed")
            self.cleanup_partial()
            return False
