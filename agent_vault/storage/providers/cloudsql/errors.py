"""Cloud SQL error handling with sanitized messages and error IDs.

This module provides error codes and exceptions for Cloud SQL operations that:
- Never expose sensitive data (IPs, credentials, internal paths, SQL queries)
- Include actionable guidance for troubleshooting
- Generate unique error IDs for support correlation
- Meet requirements FR-6.4, FR-6.5, FR-6.6, AC-12, AC-13, AC-23
"""

import uuid
from enum import Enum


class CloudSQLErrorCode(Enum):
    """Error codes with actionable guidance (FR-3.6, FR-6.6).

    Each error code is a tuple of (code, guidance) where:
    - code: String identifier for error categorization
    - guidance: User-facing actionable message (never includes sensitive data)
    """

    AUTH_FAILED = (
        "AUTH_001",
        "Authentication failed. Verify ADC: gcloud auth application-default login",
    )
    CONNECTION_FAILED = (
        "CONN_001",
        "Connection failed. Check project/region/instance config and IAM permissions",
    )
    CONFIG_INVALID = (
        "CFG_001",
        "Invalid configuration. See docs/setup/cloudsql.md for required fields",
    )
    STARTUP_FAILED = (
        "START_001",
        "Startup connectivity check failed. Verify Cloud SQL instance is running",
    )
    QUERY_FAILED = (
        "QUERY_001",
        "Database query failed. Check database user permissions",
    )

    def __init__(self, code: str, guidance: str):
        """Initialize error code with code and guidance."""
        self.error_code = code
        self.guidance = guidance


class CloudSQLError(Exception):
    """Cloud SQL error with error ID and actionable guidance (FR-6.4, FR-6.5).

    This exception class ensures that:
    - Internal details (IPs, credentials, paths, SQL) are never exposed to users
    - Each error has a unique ID for support correlation
    - Messages include actionable guidance for troubleshooting
    - repr() and str() outputs are safe for logging

    Attributes:
        code: CloudSQLErrorCode indicating error category
        error_id: 8-character UUID prefix for support correlation
        message: User-facing message with actionable guidance
        _internal_details: Internal error info (NEVER exposed to users)

    Example:
        >>> error = CloudSQLError(CloudSQLErrorCode.AUTH_FAILED, "google.auth.exceptions.DefaultCredentialsError")
        >>> print(error)
        Authentication failed. Verify ADC: gcloud auth application-default login [code: AUTH_001] Error ID: abc12345
        >>> repr(error)
        'CloudSQLError(AUTH_FAILED, error_id=abc12345)'
    """

    def __init__(self, code: CloudSQLErrorCode, internal_details: str = ""):
        """Initialize CloudSQLError.

        Args:
            code: CloudSQLErrorCode enum value indicating error category
            internal_details: Internal error information (never exposed to users)
                             Used only for internal logging/debugging
        """
        self.code = code
        self.error_id = str(uuid.uuid4())[:8]
        self._internal_details = internal_details  # Never exposed to user
        # User-facing message with actionable guidance (FR-6.6)
        self.message = f"{code.guidance} [code: {code.error_code}]"
        super().__init__(f"{self.message} Error ID: {self.error_id}")

    def __repr__(self) -> str:
        """Return representation that never exposes internal details (AC-13, AC-23).

        Returns:
            Safe string representation with error code name and error ID only
        """
        # Never expose internal details (FR-6.5, AC-13)
        return f"CloudSQLError({self.code.name}, error_id={self.error_id})"
