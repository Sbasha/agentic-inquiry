"""Connection mode detection and validation for PostgreSQL storage.

This module implements Python 3.13+ compatibility by detecting whether
cloud-sql-python-connector is available and falling back to direct asyncpg
connections when necessary. It also validates SSL configuration for security.

Design decisions:
    - Connector preferred: Use Cloud SQL connector when available
    - Graceful fallback: Direct asyncpg when connector unavailable (Python 3.13+)
    - SSL enforcement: Direct connections require ssl_mode='require' or stricter
    - Clear errors: Helpful messages guide users to correct configuration

Example:
    >>> config = BackendConfig(connection_string="postgresql://...")
    >>> mode = detect_connection_mode(config)
    >>> print(mode)  # ConnectionMode.DIRECT
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # For future type-only imports

logger = logging.getLogger(__name__)


class CloudSQLConnectorUnavailable(Exception):
    """Raised when Cloud SQL connector is required but not available."""

    pass


class SSLRequiredError(Exception):
    """Raised when direct connection requires SSL but SSL is not configured."""

    pass


class ConfigurationError(Exception):
    """Raised when configuration has conflicting or invalid options."""

    pass


class ConnectionMode(Enum):
    """Connection mode for PostgreSQL storage.

    Attributes:
        CONNECTOR: Use cloud-sql-python-connector (Python <3.13)
        DIRECT: Use direct asyncpg connection (Python 3.13+ or explicit)
    """

    CONNECTOR = "connector"
    DIRECT = "direct"


def detect_connection_mode(config: Any) -> ConnectionMode:
    """Detect which connection mode to use based on configuration and availability.

    Resolution priority:
    1. Explicit connection_string → DIRECT mode
    2. Connector available → CONNECTOR mode
    3. Connector unavailable + no connection_string → ERROR

    Args:
        config: BackendConfig with connection settings

    Returns:
        ConnectionMode enum value (CONNECTOR or DIRECT)

    Raises:
        CloudSQLConnectorUnavailable: If connector needed but not available
        SSLRequiredError: If direct connection configured without proper SSL
        ConfigurationError: If configuration has conflicting options

    Example:
        >>> # With connection_string (direct mode)
        >>> config = BackendConfig(connection_string="postgresql://...")
        >>> mode = detect_connection_mode(config)
        >>> assert mode == ConnectionMode.DIRECT
        >>>
        >>> # With project/instance (connector mode, Python <3.13)
        >>> config = BackendConfig(
        ...     project="my-project",
        ...     region="us-central1",
        ...     instance="my-instance"
        ... )
        >>> mode = detect_connection_mode(config)
        >>> assert mode == ConnectionMode.CONNECTOR
    """
    # 1. Explicit connection_string always uses direct mode
    if config.connection_string:
        _validate_direct_connection_security(config)
        logger.info("Using direct asyncpg connection (connection_string provided)")
        return ConnectionMode.DIRECT

    # 2. Check if connector is available
    try:
        from google.cloud.sql.connector import Connector  # noqa: F401

        logger.debug("Cloud SQL connector available, using connector mode")
        return ConnectionMode.CONNECTOR
    except ImportError:
        pass

    # 3. Connector unavailable - check if direct connection is configured
    if not config.connection_string:
        raise CloudSQLConnectorUnavailable(
            "The cloud-sql-python-connector package is not available.\n\n"
            "This can happen because:\n"
            "  1. The 'cloudsql' extras were not installed: "
            "pip install agent-vault[cloudsql]\n"
            "  2. Python 3.13+ is being used (connector not yet supported)\n\n"
            "Options:\n"
            "  A) Install extras: pip install agent-vault[cloudsql]\n"
            "  B) Use direct connection: Set 'connection_string' instead of "
            "'project/instance/region'\n"
            "     Note: Direct connection requires Cloud SQL Auth Proxy or "
            "public IP with SSL.\n\n"
            "See: https://docs.agent_vault.dev/cloudsql-setup#python-313"
        )

    # Should not reach here
    return ConnectionMode.DIRECT


def _validate_direct_connection_security(config: Any) -> None:
    """Validate SSL configuration for direct connections.

    Enforces SSL requirements from SEC-1:
    - ssl_mode must be 'require', 'verify-ca', or 'verify-full'
    - ssl_ca_cert required when ssl_mode='verify-full'
    - Warns about missing IAM authentication
    - Requires explicit opt-in for non-proxy direct connections

    Args:
        config: BackendConfig with SSL settings

    Raises:
        SSLRequiredError: If SSL not properly configured
        ConfigurationError: If direct connection not explicitly allowed

    Example:
        >>> # Valid configuration
        >>> config = BackendConfig(
        ...     connection_string="postgresql://...",
        ...     ssl_mode="verify-full",
        ...     ssl_ca_cert="/path/to/ca.pem",
        ...     allow_direct_connection=True
        ... )
        >>> _validate_direct_connection_security(config)  # OK
        >>>
        >>> # Invalid - no SSL
        >>> config = BackendConfig(
        ...     connection_string="postgresql://...",
        ...     ssl_mode="disable"
        ... )
        >>> _validate_direct_connection_security(config)  # Raises SSLRequiredError
    """
    # Check SSL mode (AC-13)
    ssl_mode = getattr(config, "ssl_mode", None)
    if ssl_mode in (None, "disable", "allow", "prefer"):
        raise SSLRequiredError(
            "Direct connection requires ssl_mode='require' or stricter. "
            f"Got: ssl_mode='{ssl_mode}'"
        )

    # Check CA cert for verify-full (AC-14)
    ssl_ca_cert = getattr(config, "ssl_ca_cert", None)
    if ssl_mode == "verify-full" and not ssl_ca_cert:
        raise SSLRequiredError(
            "ssl_mode='verify-full' requires ssl_ca_cert path to CA certificate"
        )

    # Validate CA cert path exists if provided
    if ssl_ca_cert:
        import os

        if not os.path.isfile(ssl_ca_cert):
            raise SSLRequiredError(
                f"ssl_ca_cert file not found: {ssl_ca_cert}. "
                "Provide a valid path to the CA certificate."
            )

    # Warn about IAM authentication (SEC-1)
    logger.warning(
        "Using direct asyncpg connection. IAM authentication is not available. "
        "For production, consider using Cloud SQL Auth Proxy."
    )

    # Check opt-in for non-proxy direct connections (SEC-1)
    allow_direct = getattr(config, "allow_direct_connection", False)
    connection_string = getattr(config, "connection_string", "")

    if not allow_direct:
        # Check if likely using proxy (localhost connection)
        if connection_string and "127.0.0.1" not in connection_string:
            raise ConfigurationError(
                "Direct connection to Cloud SQL without Auth Proxy requires "
                "explicit opt-in: set allow_direct_connection=True in config. "
                "For production, we strongly recommend using Cloud SQL Auth Proxy."
            )


def validate_config_consistency(config: Any) -> None:
    """Validate configuration doesn't have conflicting options.

    Checks for AC-17: Cannot specify both connection_string and
    Cloud SQL instance parameters.

    Args:
        config: BackendConfig to validate

    Raises:
        ConfigurationError: If conflicting options detected

    Example:
        >>> # Valid - only connection_string
        >>> config = BackendConfig(connection_string="postgresql://...")
        >>> validate_config_consistency(config)  # OK
        >>>
        >>> # Invalid - both connection methods
        >>> config = BackendConfig(
        ...     connection_string="postgresql://...",
        ...     project="my-project",
        ...     instance="my-instance"
        ... )
        >>> validate_config_consistency(config)  # Raises ConfigurationError
    """
    connection_string = getattr(config, "connection_string", None)
    project = getattr(config, "project", None)
    instance = getattr(config, "instance", None)
    region = getattr(config, "region", None)

    # AC-17: Check for conflicting connection configuration
    if connection_string and (project or instance or region):
        raise ConfigurationError(
            "Cannot specify both connection_string and Cloud SQL instance parameters "
            "(project/instance/region). Use one connection method only."
        )
