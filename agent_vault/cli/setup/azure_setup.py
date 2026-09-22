"""Azure Database for PostgreSQL setup handler for Agent-Vault.

Provides setup for Azure PostgreSQL environments with support for
native server-side embeddings via the azure_ai extension.
"""

from __future__ import annotations

import getpass
import logging
from pathlib import Path
from typing import Dict, Optional

from agent_vault.cli.setup.base import (
    BaseSetup,
    run_async,
    print_success,
    print_info,
    print_error,
    print_warning,
    prompt_input,
    prompt_confirm,
)
from agent_vault.cli.setup.templates import AZURE_TEMPLATE, render_template

logger = logging.getLogger(__name__)


# Output dimensions for the Azure OpenAI embedding deployments most
# customers run. Used to seed the default in the wizard prompt; the
# operator can still override at the prompt for custom-trained
# deployments or future model variants.
_AOAI_EMBEDDING_DIMS: Dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


def _infer_aoai_dim(deployment_name: str) -> int:
    """Best-effort inference of the AOAI embedding dim from a deployment name.

    Many customers name their deployments after the underlying model
    (`text-embedding-3-small`) — match those exactly. Anything else
    falls back to 1536 (the most common dim across Azure OpenAI
    embedding deployments) and the wizard prompt lets the operator
    override.
    """
    return _AOAI_EMBEDDING_DIMS.get(deployment_name, 1536)


class AzureSetup(BaseSetup):
    """Setup handler for Azure Database for PostgreSQL environments.

    Creates an Azure-backed environment with:
    - Direct connection to Azure PostgreSQL
    - Optional server-side embedding support via azure_ai extension
    - pgvector extension for vector storage

    Example:
        >>> setup = AzureSetup(env_name="azure-prod")
        >>> setup.run()
        True
    """

    backend_type = "azure"

    def __init__(
        self,
        env_name: Optional[str] = None,
        is_dev: bool = False,
        workspace: Optional[Path] = None,
        host: Optional[str] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        table_prefix: Optional[str] = None,
        embedding_strategy: str = "server_side",
        embedding_model: Optional[str] = None,
        embedding_dim: Optional[int] = None,
    ) -> None:
        """Initialize Azure PostgreSQL setup.

        Args:
            env_name: Environment name
            is_dev: If True, creates a test environment
            workspace: Workspace root path
            host: Azure PostgreSQL hostname
            database: Database name (default: agent-vault)
            user: Database username
            password: Database password
            table_prefix: Table prefix for isolation (default: agv_)
            embedding_strategy: ``"server_side"`` (default — uses the
                ``azure_ai`` extension to embed in-database) or
                ``"local"`` (client-side SentenceTransformer; rare for
                Azure deployments — if you want LOCAL embedding,
                ``postgresql`` backend is usually the simpler choice).
            embedding_model: Azure OpenAI deployment name for server-side embeddings
            embedding_dim: Output dim of the Azure OpenAI deployment.
                Defaults to 1536 (text-embedding-3-small / ada-002);
                pass 3072 for text-embedding-3-large.
        """
        super().__init__(env_name=env_name, is_dev=is_dev, workspace=workspace)
        self._host = host
        self._database = database
        self._user = user
        self._password = password
        self._table_prefix = table_prefix or "agv_"
        self._embedding_strategy = embedding_strategy
        self._embedding_model = embedding_model
        self._embedding_dim = embedding_dim

    def run(self) -> bool:
        """Run the Azure PostgreSQL setup wizard."""
        try:
            print_info(f"\n--- Setting up Azure PostgreSQL Environment: {self.env_name} ---")

            # 1. Connection Details
            if not self._host:
                self._host = prompt_input(
                    "Azure PostgreSQL Host (e.g., my-server.postgres.database.azure.com)",
                    required=True
                )

            if not self._database:
                self._database = prompt_input("Database name", default="agent-vault")

            if not self._user:
                self._user = prompt_input("Database user", required=True)

            if not self._password:
                self._password = getpass.getpass("Database password: ")

            # 2. Embedding Strategy. Server-side is the recommended
            # default for Azure — running on Azure Postgres without
            # using ``azure_ai`` is a configuration most teams should
            # instead express as the plain ``postgresql`` backend.
            if prompt_confirm(
                "Enable native server-side embeddings via Azure OpenAI? (recommended)",
                default=True,
            ):
                self._embedding_strategy = "server_side"
                if not self._embedding_model:
                    self._embedding_model = prompt_input(
                        "Azure OpenAI Deployment Name (e.g., text-embedding-3-small)",
                        default="text-embedding-3-small",
                        required=True,
                    )
                if self._embedding_dim is None:
                    # Infer for the two common AOAI embedding models;
                    # prompt with the inferred default otherwise. The
                    # input loop reprompts on non-numeric / non-positive
                    # responses so a typo doesn't abort the whole wizard
                    # via the outer ``except Exception`` handler.
                    inferred = _infer_aoai_dim(self._embedding_model)
                    while True:
                        dim_str = prompt_input(
                            f"Embedding dimension for '{self._embedding_model}'",
                            default=str(inferred),
                            required=True,
                        )
                        stripped = (dim_str or "").strip()
                        if stripped.isdigit() and int(stripped) > 0:
                            self._embedding_dim = int(stripped)
                            break
                        print_warning(
                            "Embedding dimension must be a positive "
                            "integer (e.g. 1536 for text-embedding-3-small, "
                            "3072 for text-embedding-3-large). "
                            f"Got {dim_str!r}; please try again."
                        )
            else:
                self._embedding_strategy = "local"
                self._embedding_model = ""
                # Local path uses the SentenceTransformer default dim.
                # If the user later reconfigures, validate_embedding_consistency
                # catches the dim mismatch.
                self._embedding_dim = 384

            # 3. Connection Test & Extension Check
            print_info("\nTesting connection and checking extensions...")
            success = run_async(self._verify_and_initialize())
            if not success:
                return False

            # 4. Generate Configuration
            config = render_template(
                AZURE_TEMPLATE,
                {
                    "ENV_NAME": self.env_name,
                    "root": str(self.env_dir),
                    "AZURE_HOST": self._host,
                    "AZURE_DATABASE": self._database,
                    "AZURE_USER": self._user,
                    "TABLE_PREFIX": self._table_prefix,
                    "EMBEDDING_STRATEGY": self._embedding_strategy,
                    "EMBEDDING_MODEL": self._embedding_model or "",
                    "EMBEDDING_DIM": str(self._embedding_dim or 1536),
                }
            )
            # Coerce numeric fields that the template rendered as strings.
            azure_backend = config["storage"]["backends"]["azure_db"]
            if isinstance(azure_backend.get("embedding_dim"), str):
                azure_backend["embedding_dim"] = int(
                    azure_backend["embedding_dim"]
                )
            # Default-provider + default_dimensions track the *active*
            # path: server-side → "none" sentinel + AOAI dim;
            # local → sentence_transformer at 384.
            if self._embedding_strategy == "local":
                config["embeddings"]["default_provider"] = "sentence_transformer"
                config["embeddings"]["default_dimensions"] = 384
            else:
                config["embeddings"]["default_provider"] = "none"
                config["embeddings"]["default_dimensions"] = (
                    self._embedding_dim or 1536
                )

            # 5. Save Environment
            self.create_env_directory()
            self.write_config(config)
            
            # Save password to .env for the environment
            env_content = (
                f"DB_PASSWORD={self._password}\n"
                f"AZURE_POSTGRES_HOST={self._host}\n"
            )
            self._save_env_vars(env_content)

            self.register_environment(metadata={
                "setup_type": "azure",
                "host": self._host,
                "database": self._database,
                "embedding_strategy": self._embedding_strategy,
            })
            self.set_active()

            print_success(f"\nAzure PostgreSQL environment '{self.env_name}' configured successfully!")
            return True

        except Exception as e:
            print_error(f"Azure setup failed: {e}")
            return False

    def _save_env_vars(self, content: str) -> None:
        """Save environment variables to .env file."""
        env_path = self.env_dir / ".env"
        try:
            with open(env_path, "w") as f:
                f.write(content)
            logger.info("Environment variables written to: %s", env_path)
        except Exception as e:
            logger.error("Failed to write .env file: %s", e)

    async def _verify_and_initialize(self) -> bool:
        """Verify connection and ensure extensions exist."""
        from agent_vault.storage.providers.postgresql.connection import PostgresConnectionManager
        from agent_vault.storage.providers.postgresql.adapter import AzurePostgresAdapter
        
        # Build connection string (manually for setup verification)
        from urllib.parse import quote
        dsn = f"postgresql://{self._user}:{quote(str(self._password), safe='')}@{self._host}:5432/{self._database}?sslmode=require"
        
        manager = PostgresConnectionManager(connection_string=dsn, table_prefix=self._table_prefix)
        
        try:
            await manager.initialize()
            
            # Check for required extensions. The adapter filters its
            # extension list based on the chosen strategy — LOCAL
            # Azure skips ``azure_ai`` (it isn't needed if embeddings
            # run client-side). The wizard passes the strategy
            # explicitly so this matches the runtime provider's
            # behaviour.
            adapter = AzurePostgresAdapter()
            for ext in adapter.required_extensions(self._embedding_strategy):
                print_info(f"Ensuring extension '{ext}' is installed...")
                await manager.ensure_extension(ext)
                
            # Perform a test search if server-side enabled
            if self._embedding_strategy == "server_side":
                print_info(f"Verifying Azure OpenAI integration with model '{self._embedding_model}'...")
                test_sql = f"SELECT {adapter.get_embedding_sql('$1', self._embedding_model)} as vec"
                try:
                    await manager.fetch(test_sql, "test connection")
                    print_success("Azure OpenAI embedding test successful!")
                except Exception as e:
                    print_warning(f"Could not verify Azure OpenAI embedding: {e}")
                    print_warning("Please ensure 'azure_ai' extension is configured with your API key.")
            
            await manager.close()
            return True
            
        except Exception as e:
            print_error(f"Connection verification failed: {e}")
            return False
