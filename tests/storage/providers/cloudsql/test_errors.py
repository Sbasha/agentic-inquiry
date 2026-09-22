"""Tests for Cloud SQL error handling, sanitization, and credential safety.

This module tests:
- CloudSQLError structure (error_id, messages, repr/str)
- Error sanitization (no credentials, IPs, SQL queries leaked)
- Error code completeness and guidance

Implements AC-12, AC-13, AC-23 from gcp-native spec.
"""

import re
import pytest

pytestmark = pytest.mark.unit

from agent_vault.storage.providers.cloudsql.errors import (
    CloudSQLError,
    CloudSQLErrorCode,
)


def test_cloudsql_error_has_error_id():
    """Test that CloudSQLError generates an error_id that is exactly 8 characters.

    Verifies AC-12: Error IDs for support correlation.
    """
    error = CloudSQLError(CloudSQLErrorCode.AUTH_FAILED)

    # Error ID should exist
    assert hasattr(error, "error_id")
    assert error.error_id is not None

    # Error ID should be exactly 8 characters (UUID prefix)
    assert len(error.error_id) == 8

    # Error ID should be alphanumeric (UUID format)
    assert re.match(r"^[a-f0-9]{8}$", error.error_id)


def test_cloudsql_error_message_has_guidance():
    """Test that CloudSQLError messages contain actionable guidance.

    Verifies AC-12: Actionable troubleshooting guidance.
    """
    error = CloudSQLError(CloudSQLErrorCode.AUTH_FAILED)

    # Message should contain the guidance from the error code
    assert CloudSQLErrorCode.AUTH_FAILED.guidance in error.message

    # Message should contain the error code
    assert CloudSQLErrorCode.AUTH_FAILED.error_code in error.message

    # String representation should include error ID
    error_str = str(error)
    assert error.error_id in error_str
    assert CloudSQLErrorCode.AUTH_FAILED.guidance in error_str


def test_cloudsql_error_repr_hides_internal():
    """Test that repr() never exposes internal details.

    Verifies AC-13: Internal details never exposed in repr().
    """
    # Create error with sensitive internal details
    sensitive_data = "Connection failed to 10.20.30.40:5432 with user sa-test@project.iam.gserviceaccount.com"
    error = CloudSQLError(CloudSQLErrorCode.CONNECTION_FAILED, internal_details=sensitive_data)

    repr_output = repr(error)

    # repr() should NOT contain internal details
    assert sensitive_data not in repr_output
    assert "10.20.30.40" not in repr_output
    assert "sa-test@project.iam.gserviceaccount.com" not in repr_output

    # repr() should only contain safe information
    assert "CloudSQLError" in repr_output
    assert error.code.name in repr_output
    assert error.error_id in repr_output

    # Verify expected format: CloudSQLError(CODE_NAME, error_id=abc12345)
    assert re.match(r"CloudSQLError\(\w+, error_id=[a-f0-9]{8}\)", repr_output)


def test_cloudsql_error_str_hides_internal():
    """Test that str() never exposes internal details.

    Verifies AC-13: Internal details never exposed in user-facing strings.
    """
    # Create error with sensitive internal details
    sensitive_data = "SQL: SELECT * FROM users WHERE password='secret123'"
    error = CloudSQLError(CloudSQLErrorCode.QUERY_FAILED, internal_details=sensitive_data)

    str_output = str(error)

    # str() should NOT contain internal details
    assert sensitive_data not in str_output
    assert "SELECT * FROM users" not in str_output
    assert "password='secret123'" not in str_output

    # str() should only contain safe information
    assert error.code.guidance in str_output
    assert error.code.error_code in str_output
    assert error.error_id in str_output


def test_all_error_codes_have_guidance():
    """Test that all CloudSQLErrorCode enum members have non-empty guidance.

    Verifies completeness of error code definitions.
    """
    # Get all error codes
    error_codes = list(CloudSQLErrorCode)

    # Should have at least 5 error codes defined
    assert len(error_codes) >= 5

    # Every error code should have guidance
    for code in error_codes:
        assert hasattr(code, "error_code")
        assert hasattr(code, "guidance")

        # Error code should be non-empty string
        assert isinstance(code.error_code, str)
        assert len(code.error_code) > 0

        # Guidance should be non-empty string
        assert isinstance(code.guidance, str)
        assert len(code.guidance) > 0

        # Guidance should be actionable (contain some helpful words)
        # Check for common actionable phrases
        guidance_lower = code.guidance.lower()
        actionable_keywords = [
            "verify", "check", "see", "ensure", "confirm",
            "try", "use", "run", "configure", "set",
            "permission", "config", "document", "auth"
        ]
        assert any(keyword in guidance_lower for keyword in actionable_keywords), \
            f"Error code {code.name} guidance should contain actionable advice"


def test_error_message_no_credentials():
    """Test that error messages never contain credential information.

    Verifies AC-23: Credential leak prevention (security requirement).
    Tests for:
    - IP addresses (IPv4 pattern)
    - Service account emails
    - File paths
    - Connection strings with passwords
    """
    # Test cases with various sensitive data types
    test_cases = [
        ("IP address", "Failed to connect to 192.168.1.100:5432"),
        ("Service account", "Auth failed for sa-dev@my-project.iam.gserviceaccount.com"),
        ("File path", "Could not read /home/user/secrets/credentials.json"),
        ("Connection string", "postgresql://user:password123@host:5432/db"),
        ("Another IP", "Connection refused from 10.0.0.5"),
    ]

    for test_name, sensitive_internal_data in test_cases:
        error = CloudSQLError(CloudSQLErrorCode.CONNECTION_FAILED, internal_details=sensitive_internal_data)

        # Check str() output
        str_output = str(error)

        # Should not contain IP addresses
        ip_pattern = r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
        assert not re.search(ip_pattern, str_output), \
            f"Error message contains IP address ({test_name}): {str_output}"

        # Should not contain service account emails
        service_account_pattern = r"\S+@\S+\.iam\.gserviceaccount\.com"
        assert not re.search(service_account_pattern, str_output), \
            f"Error message contains service account email ({test_name}): {str_output}"

        # Should not contain file paths (Unix or Windows style)
        # Look for absolute paths with common credential file patterns
        path_pattern = r"(?:/(?:home|var|etc|opt|usr|path|Users)/[\w/.-]+|[A-Z]:\\[\w\\.-]+)"
        assert not re.search(path_pattern, str_output), \
            f"Error message contains file path ({test_name}): {str_output}"

        # Should not contain connection strings with passwords
        conn_string_pattern = r"postgresql://\S+:\S+@"
        assert not re.search(conn_string_pattern, str_output), \
            f"Error message contains connection string with password ({test_name}): {str_output}"

        # Check repr() output
        repr_output = repr(error)

        # repr() should also not leak credentials
        assert not re.search(ip_pattern, repr_output), \
            f"Error repr contains IP address ({test_name}): {repr_output}"
        assert not re.search(service_account_pattern, repr_output), \
            f"Error repr contains service account email ({test_name}): {repr_output}"

        # Check message attribute
        assert not re.search(ip_pattern, error.message), \
            f"Error.message contains IP address ({test_name}): {error.message}"
        assert not re.search(service_account_pattern, error.message), \
            f"Error.message contains service account email ({test_name}): {error.message}"


def test_error_message_no_sql_query():
    """Test that error messages never contain SQL queries.

    Verifies AC-23: SQL query sanitization (prevents data leakage).
    """
    # Test cases with various SQL queries
    sql_queries = [
        "SELECT * FROM users WHERE email = 'admin@example.com'",
        "INSERT INTO sessions (user_id, token) VALUES (123, 'abc123')",
        "UPDATE config SET api_key = 'secret' WHERE id = 1",
        "DELETE FROM logs WHERE timestamp < '2024-01-01'",
        "CREATE TABLE sensitive_data (id INT, secret TEXT)",
    ]

    for sql_query in sql_queries:
        error = CloudSQLError(CloudSQLErrorCode.QUERY_FAILED, internal_details=sql_query)

        # Check str() output
        str_output = str(error)

        # Should not contain any part of the SQL query
        assert sql_query not in str_output, \
            f"Error message contains SQL query: {str_output}"

        # Should not contain SQL keywords that might leak query structure
        # Only check if they appear in a SQL-like context (with surrounding SQL keywords)
        sql_keyword_pattern = r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\s+\w+"
        assert not re.search(sql_keyword_pattern, str_output, re.IGNORECASE), \
            f"Error message contains SQL keywords: {str_output}"

        # Check repr() output
        repr_output = repr(error)
        assert sql_query not in repr_output, \
            f"Error repr contains SQL query: {repr_output}"

        # Check message attribute
        assert sql_query not in error.message, \
            f"Error.message contains SQL query: {error.message}"


def test_error_internal_details_not_accessible():
    """Test that internal_details attribute is private and not exposed.

    Additional security verification beyond AC-23.
    """
    sensitive_data = "Password: super_secret_123"
    error = CloudSQLError(CloudSQLErrorCode.AUTH_FAILED, internal_details=sensitive_data)

    # _internal_details should exist but be private
    assert hasattr(error, "_internal_details")
    assert error._internal_details == sensitive_data

    # But it should not be exposed in public interfaces
    error_dict = vars(error)
    public_attrs = [k for k in error_dict.keys() if not k.startswith("_")]

    # Public attributes should not contain the sensitive data
    for attr_name in public_attrs:
        attr_value = getattr(error, attr_name)
        if isinstance(attr_value, str):
            assert sensitive_data not in attr_value, \
                f"Sensitive data exposed in public attribute '{attr_name}'"


def test_multiple_errors_have_unique_ids():
    """Test that each error instance gets a unique error_id.

    Verifies AC-12: Unique error IDs for support correlation.
    """
    errors = [CloudSQLError(CloudSQLErrorCode.AUTH_FAILED) for _ in range(10)]

    error_ids = [e.error_id for e in errors]

    # All error IDs should be unique
    assert len(error_ids) == len(set(error_ids)), \
        "Error IDs should be unique across instances"


def test_error_code_enum_coverage():
    """Test that CloudSQLErrorCode covers expected error categories.

    Verifies completeness of error handling.
    """
    expected_categories = {
        "AUTH_FAILED",
        "CONNECTION_FAILED",
        "CONFIG_INVALID",
        "STARTUP_FAILED",
        "QUERY_FAILED",
    }

    actual_categories = {code.name for code in CloudSQLErrorCode}

    # All expected categories should be present
    assert expected_categories.issubset(actual_categories), \
        f"Missing error codes: {expected_categories - actual_categories}"
