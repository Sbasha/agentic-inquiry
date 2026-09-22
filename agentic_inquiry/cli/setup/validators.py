"""Connection validators for setup wizard.

Provides async validation functions for database connections used during setup.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def validate_postgres_connection(connection_string: str) -> tuple[bool, str]:
    """Validate a PostgreSQL connection string.

    Attempts to connect to the database and execute a simple query.

    Args:
        connection_string: PostgreSQL connection string
            (e.g., postgresql://user:pass@localhost:5432/dbname)

    Returns:
        Tuple of (success, message):
        - (True, "Connected successfully") on success
        - (False, "error message") on failure

    Example:
        >>> success, msg = await validate_postgres_connection(
        ...     "postgresql://user:pass@localhost/db"
        ... )
        >>> if success:
        ...     print("Connection OK")
    """
    try:
        import asyncpg
    except ImportError:
        return False, "asyncpg is required for PostgreSQL. Install with: pip install asyncpg"

    try:
        # Create a connection with timeout
        conn = await asyncio.wait_for(
            asyncpg.connect(connection_string),
            timeout=10.0,
        )
        try:
            # Simple connectivity test
            result = await conn.fetchval("SELECT 1")
            if result == 1:
                return True, "Connected successfully"
            return False, "Unexpected response from database"
        finally:
            await conn.close()

    except asyncio.TimeoutError:
        return False, "Connection timed out after 10 seconds"
    except asyncpg.InvalidCatalogNameError as e:
        return False, f"Database not found: {e}"
    except asyncpg.InvalidPasswordError:
        return False, "Invalid password"
    except asyncpg.PostgresConnectionError as e:
        error_str = str(e).lower()
        if "refused" in error_str:
            return False, "Connection refused. Check host and port."
        return False, f"Connection failed: {e}"
    except Exception as e:
        # Sanitize error message (don't expose connection details)
        error_type = type(e).__name__
        return False, f"Connection failed: {error_type}"


async def check_pgvector_extension(connection_string: str) -> bool:
    """Check if the pgvector extension is installed.

    Args:
        connection_string: PostgreSQL connection string

    Returns:
        True if pgvector extension exists, False otherwise

    Example:
        >>> has_vector = await check_pgvector_extension(conn_str)
        >>> if not has_vector:
        ...     print("pgvector not installed")
    """
    try:
        import asyncpg

        conn = await asyncio.wait_for(
            asyncpg.connect(connection_string),
            timeout=10.0,
        )
        try:
            result = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            )
            return bool(result)
        finally:
            await conn.close()

    except Exception as e:
        logger.warning("Failed to check pgvector extension: %s", e)
        return False


async def create_pgvector_extension(connection_string: str) -> tuple[bool, str]:
    """Create the pgvector extension if user has privileges.

    Args:
        connection_string: PostgreSQL connection string

    Returns:
        Tuple of (success, message)

    Example:
        >>> success, msg = await create_pgvector_extension(conn_str)
        >>> if success:
        ...     print("pgvector extension created")
    """
    try:
        import asyncpg

        conn = await asyncio.wait_for(
            asyncpg.connect(connection_string),
            timeout=10.0,
        )
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            return True, "pgvector extension created"
        finally:
            await conn.close()

    except asyncpg.InsufficientPrivilegeError:
        return False, (
            "Insufficient privileges to create extension. "
            "Run as superuser: CREATE EXTENSION vector;"
        )
    except Exception as e:
        error_type = type(e).__name__
        return False, f"Failed to create extension: {error_type}"


async def check_database_exists(connection_string: str) -> bool:
    """Check if the database exists.

    Attempts connection to verify database accessibility.

    Args:
        connection_string: PostgreSQL connection string

    Returns:
        True if database exists and is accessible
    """
    success, _ = await validate_postgres_connection(connection_string)
    return success


async def validate_cloudsql_connection(
    project: str,
    region: str,
    instance: str,
    database: str,
    user: str,
    timeout: float = 30.0,
) -> tuple[bool, str]:
    """Validate a Cloud SQL connection using the Cloud SQL Connector.

    Uses ADC (Application Default Credentials) for authentication.

    Args:
        project: GCP project ID
        region: GCP region
        instance: Cloud SQL instance name
        database: Database name
        user: IAM database user
        timeout: Connection timeout in seconds

    Returns:
        Tuple of (success, message)

    Example:
        >>> success, msg = await validate_cloudsql_connection(
        ...     project="my-project",
        ...     region="us-central1",
        ...     instance="my-instance",
        ...     database="ai",
        ...     user="ai-user@my-project.iam",
        ... )
    """
    try:
        import asyncpg
        from google.cloud.sql.connector import Connector
    except ImportError:
        return False, (
            "google-cloud-sql-connector is required for Cloud SQL. "
            "Install with: pip install google-cloud-sql-connector[asyncpg]"
        )

    try:
        import google.auth
    except ImportError:
        return False, (
            "google-auth is required for Cloud SQL. "
            "Install with: pip install google-auth"
        )

    instance_connection_name = f"{project}:{region}:{instance}"

    try:
        # Initialize connector
        connector = Connector()

        try:
            # Create connection with IAM auth
            async def getconn():
                return await connector.connect_async(
                    instance_connection_name,
                    "asyncpg",
                    user=user,
                    db=database,
                    enable_iam_auth=True,
                )

            # Test connection with timeout
            conn = await asyncio.wait_for(getconn(), timeout=timeout)

            try:
                # Simple connectivity test
                result = await conn.fetchval("SELECT 1")
                if result == 1:
                    return True, "Connected successfully via Cloud SQL Connector"
                return False, "Unexpected response from database"
            finally:
                await conn.close()

        finally:
            await connector.close_async()

    except asyncio.TimeoutError:
        return False, f"Connection timed out after {timeout} seconds"
    except google.auth.exceptions.DefaultCredentialsError:
        return False, (
            "ADC not configured. Run: gcloud auth application-default login"
        )
    except Exception as e:
        error_type = type(e).__name__
        # Check for common error patterns
        error_str = str(e).lower()
        if "permission denied" in error_str:
            return False, (
                f"Permission denied. Ensure user '{user}' has IAM database access. "
                "Grant roles/cloudsql.instanceUser role."
            )
        if "not found" in error_str:
            return False, f"Instance not found: {instance_connection_name}"
        return False, f"Connection failed: {error_type}"


def validate_connection_string_format(connection_string: str) -> tuple[bool, Optional[str]]:
    """Validate PostgreSQL connection string format.

    Checks basic format without attempting connection.

    Args:
        connection_string: Connection string to validate

    Returns:
        Tuple of (valid, error_message or None)

    Example:
        >>> valid, err = validate_connection_string_format(
        ...     "postgresql://user:pass@host/db"
        ... )
        >>> if not valid:
        ...     print(f"Invalid: {err}")
    """
    import re

    # Basic format: postgresql://[user[:password]@]host[:port]/database
    pattern = r"^postgresql(?:\+asyncpg)?://(?:[^:]+(?::[^@]+)?@)?[^/]+/\w+"

    if not connection_string:
        return False, "Connection string is required"

    if not connection_string.startswith(("postgresql://", "postgres://")):
        return False, "Connection string must start with postgresql:// or postgres://"

    # Check for common mistakes
    if "@localhost/" not in connection_string and "@127.0.0.1/" not in connection_string:
        if "localhost" in connection_string or "127.0.0.1" in connection_string:
            # Might be missing port or db
            pass

    # Check for missing database
    if connection_string.count("/") < 3:
        parts = connection_string.split("/")
        if len(parts) < 4 or not parts[-1]:
            return False, "Connection string must include database name (e.g., /dbname)"

    return True, None


async def validate_rds_connection(
    host: str,
    port: int,
    database: str,
    user: str,
    password: Optional[str] = None,
    use_iam_auth: bool = False,
    region: Optional[str] = None,
    instance: Optional[str] = None,
    timeout: float = 15.0,
) -> tuple[bool, str]:
    """Validate an AWS RDS connection.

    Attempts to connect to the RDS instance via SSL and execute a simple query.
    Supports both password and IAM token authentication.

    Args:
        host: RDS endpoint hostname
        port: Port number (default 5432)
        database: Database name
        user: Database username
        password: Database password (None when use_iam_auth is True)
        use_iam_auth: Generate an IAM authentication token via boto3
        region: AWS region (required for IAM auth)
        instance: RDS instance identifier (unused, for future use)
        timeout: Connection timeout in seconds

    Returns:
        Tuple of (success, message)

    Example:
        >>> success, msg = await validate_rds_connection(
        ...     host="mydb.xxxxx.us-east-1.rds.amazonaws.com",
        ...     port=5432,
        ...     database="agentic-inquiry",
        ...     user="ai_user",
        ...     password="secret",
        ... )
    """
    try:
        import asyncpg
    except ImportError:
        return False, "asyncpg is required for RDS. Install with: pip install asyncpg"

    resolved_password = password

    if use_iam_auth:
        try:
            import boto3
        except ImportError:
            return False, (
                "boto3 is required for AWS IAM authentication. "
                "Install with: pip install boto3"
            )
        try:
            rds_client = boto3.client("rds", region_name=region)
            resolved_password = rds_client.generate_db_auth_token(
                DBHostname=host,
                Port=port,
                DBUsername=user,
                Region=region,
            )
        except Exception as e:
            error_type = type(e).__name__
            return False, f"Failed to generate IAM auth token: {error_type}"

    try:
        ssl_ctx = True  # asyncpg accepts True for basic SSL (require mode)
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host=host,
                port=port,
                user=user,
                password=resolved_password,
                database=database,
                ssl=ssl_ctx,
            ),
            timeout=timeout,
        )
        try:
            result = await conn.fetchval("SELECT 1")
            if result == 1:
                auth_method = "IAM token" if use_iam_auth else "password"
                return True, f"Connected successfully via SSL ({auth_method} auth)"
            return False, "Unexpected response from database"
        finally:
            await conn.close()

    except asyncio.TimeoutError:
        return False, f"Connection timed out after {timeout} seconds"
    except asyncpg.InvalidCatalogNameError as e:
        return False, f"Database not found: {e}"
    except asyncpg.InvalidPasswordError:
        return False, "Invalid password or IAM auth token"
    except asyncpg.PostgresConnectionError as e:
        error_str = str(e).lower()
        if "refused" in error_str:
            return False, "Connection refused — check host, port, and security group rules"
        return False, f"Connection failed: {e}"
    except Exception as e:
        error_type = type(e).__name__
        return False, f"Connection failed: {error_type}"
