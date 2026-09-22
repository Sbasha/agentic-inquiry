"""AWS utilities for setup wizard.

Provides wrapper functions for AWS CLI and boto3 operations used during
AWS RDS setup.
"""

from __future__ import annotations

import json
import logging
import subprocess
import shutil
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AWSAuthInfo:
    """AWS authentication information."""

    account_id: str
    arn: str
    user_id: str

    @property
    def is_iam_role(self) -> bool:
        """Return True if authenticated as an IAM role (assumed-role)."""
        return ":assumed-role/" in self.arn

    @property
    def display_name(self) -> str:
        """Short display name derived from the ARN."""
        return self.arn.split("/")[-1]


@dataclass
class RDSInstance:
    """AWS RDS instance information."""

    identifier: str
    engine: str
    engine_version: str
    status: str
    endpoint_host: str
    endpoint_port: int
    region: str
    db_name: Optional[str]

    @property
    def display_name(self) -> str:
        """Display name for user selection."""
        return f"{self.identifier} ({self.endpoint_host}, {self.engine} {self.engine_version})"


def check_aws_cli_installed() -> bool:
    """Check if the AWS CLI is installed and available.

    Returns:
        True if the AWS CLI is available in PATH

    Example:
        >>> if not check_aws_cli_installed():
        ...     print("Please install the AWS CLI")
    """
    return shutil.which("aws") is not None


def check_aws_auth() -> Optional[AWSAuthInfo]:
    """Check if the AWS CLI is authenticated with valid credentials.

    Calls ``aws sts get-caller-identity`` to verify credentials.

    Returns:
        AWSAuthInfo with account details, or None if not authenticated

    Example:
        >>> auth = check_aws_auth()
        >>> if auth:
        ...     print(f"Logged in as: {auth.display_name}")
    """
    if not check_aws_cli_installed():
        return None

    try:
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--output", "json"],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode != 0:
            logger.debug("aws sts get-caller-identity failed: %s", result.stderr)
            return None

        data = json.loads(result.stdout)
        return AWSAuthInfo(
            account_id=data.get("Account", ""),
            arn=data.get("Arn", ""),
            user_id=data.get("UserId", ""),
        )

    except subprocess.TimeoutExpired:
        logger.warning("aws sts get-caller-identity timed out")
        return None
    except json.JSONDecodeError:
        logger.warning("Failed to parse aws sts output")
        return None
    except Exception as e:
        logger.debug("AWS auth check failed: %s", e)
        return None


def get_current_region() -> Optional[str]:
    """Get the currently configured AWS region.

    Checks the AWS_DEFAULT_REGION env var, then the AWS CLI config.

    Returns:
        Region string (e.g. "us-east-1") or None if not configured

    Example:
        >>> region = get_current_region()
        >>> if region:
        ...     print(f"Current region: {region}")
    """
    import os

    # Check environment variable first
    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION")
    if region:
        return region

    if not check_aws_cli_installed():
        return None

    try:
        result = subprocess.run(
            ["aws", "configure", "get", "region"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            value = result.stdout.strip()
            return value if value else None

        return None

    except subprocess.TimeoutExpired:
        logger.warning("aws configure get region timed out")
        return None
    except Exception as e:
        logger.debug("aws configure get region failed: %s", e)
        return None


def list_rds_instances(region: Optional[str] = None) -> list[RDSInstance]:
    """List RDS PostgreSQL instances visible to the current AWS credentials.

    Args:
        region: AWS region to query (uses configured default if None)

    Returns:
        List of RDSInstance objects for PostgreSQL-compatible engines

    Example:
        >>> instances = list_rds_instances("us-east-1")
        >>> for inst in instances:
        ...     print(inst.display_name)
    """
    if not check_aws_cli_installed():
        return []

    cmd = [
        "aws", "rds", "describe-db-instances",
        "--output", "json",
    ]
    if region:
        cmd.extend(["--region", region])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.debug("aws rds describe-db-instances failed: %s", result.stderr)
            return []

        data = json.loads(result.stdout)
        instances = []

        for db in data.get("DBInstances", []):
            engine = db.get("Engine", "")
            # Only include PostgreSQL-compatible engines
            if engine not in ("postgres", "aurora-postgresql"):
                continue

            endpoint = db.get("Endpoint", {})
            host = endpoint.get("Address", "")
            port = int(endpoint.get("Port", 5432))
            # Region: strip trailing AZ letter from AvailabilityZone (e.g. "us-east-1a" → "us-east-1")
            az = db.get("AvailabilityZone", "")
            effective_region = region or (az[:-1] if az and az[-1].isalpha() else az)

            instances.append(RDSInstance(
                identifier=db.get("DBInstanceIdentifier", ""),
                engine=engine,
                engine_version=db.get("EngineVersion", ""),
                status=db.get("DBInstanceStatus", "unknown"),
                endpoint_host=host,
                endpoint_port=port,
                region=effective_region,
                db_name=db.get("DBName"),
            ))

        return instances

    except subprocess.TimeoutExpired:
        logger.warning("aws rds describe-db-instances timed out")
        return []
    except json.JSONDecodeError:
        logger.warning("Failed to parse aws rds output")
        return []
    except Exception as e:
        logger.debug("aws rds describe-db-instances failed: %s", e)
        return []


def check_iam_auth_enabled(
    instance_identifier: str,
    region: Optional[str] = None,
) -> bool:
    """Check if IAM database authentication is enabled on an RDS instance.

    Args:
        instance_identifier: RDS instance identifier
        region: AWS region (uses configured default if None)

    Returns:
        True if IAM authentication is enabled

    Example:
        >>> enabled = check_iam_auth_enabled("my-db", "us-east-1")
    """
    if not check_aws_cli_installed():
        return False

    cmd = [
        "aws", "rds", "describe-db-instances",
        "--db-instance-identifier", instance_identifier,
        "--output", "json",
    ]
    if region:
        cmd.extend(["--region", region])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode != 0:
            return False

        data = json.loads(result.stdout)
        dbs = data.get("DBInstances", [])
        if not dbs:
            return False

        return bool(dbs[0].get("IAMDatabaseAuthenticationEnabled", False))

    except Exception as e:
        logger.debug("Failed to check IAM auth for %s: %s", instance_identifier, e)
        return False
