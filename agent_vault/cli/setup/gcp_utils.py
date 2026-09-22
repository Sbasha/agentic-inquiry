"""GCP utilities for setup wizard.

Provides wrapper functions for gcloud CLI operations used during GCP/CloudSQL setup.
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
class GCPAuthInfo:
    """GCP authentication information."""

    account: str
    project: Optional[str] = None
    is_service_account: bool = False


@dataclass
class CloudSQLInstance:
    """Cloud SQL instance information."""

    name: str
    project: str
    region: str
    database_version: str
    state: str
    connection_name: str

    @property
    def display_name(self) -> str:
        """Display name for user selection."""
        return f"{self.name} ({self.region}, {self.database_version})"


def check_gcloud_installed() -> bool:
    """Check if gcloud CLI is installed and available.

    Returns:
        True if gcloud is available in PATH

    Example:
        >>> if not check_gcloud_installed():
        ...     print("Please install gcloud CLI")
    """
    return shutil.which("gcloud") is not None


def check_gcloud_auth() -> Optional[GCPAuthInfo]:
    """Check if gcloud is authenticated with valid credentials.

    Returns:
        GCPAuthInfo with account details, or None if not authenticated

    Example:
        >>> auth = check_gcloud_auth()
        >>> if auth:
        ...     print(f"Logged in as: {auth.account}")
    """
    if not check_gcloud_installed():
        return None

    try:
        # Get active account
        result = subprocess.run(
            ["gcloud", "auth", "list", "--format=json"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            logger.debug("gcloud auth list failed: %s", result.stderr)
            return None

        accounts = json.loads(result.stdout)

        # Find active account
        for acc in accounts:
            if acc.get("status") == "ACTIVE":
                account = acc.get("account", "")
                return GCPAuthInfo(
                    account=account,
                    is_service_account="@" in account and "iam.gserviceaccount.com" in account,
                )

        return None

    except subprocess.TimeoutExpired:
        logger.warning("gcloud auth check timed out")
        return None
    except json.JSONDecodeError:
        logger.warning("Failed to parse gcloud auth output")
        return None
    except Exception as e:
        logger.debug("gcloud auth check failed: %s", e)
        return None


def get_current_project() -> Optional[str]:
    """Get the currently configured GCP project.

    Returns:
        Project ID or None if not set

    Example:
        >>> project = get_current_project()
        >>> if project:
        ...     print(f"Current project: {project}")
    """
    if not check_gcloud_installed():
        return None

    try:
        result = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            project = result.stdout.strip()
            return project if project else None

        return None

    except subprocess.TimeoutExpired:
        logger.warning("gcloud config get timed out")
        return None
    except Exception as e:
        logger.debug("gcloud config get failed: %s", e)
        return None


def list_cloudsql_instances(project: str) -> list[CloudSQLInstance]:
    """List Cloud SQL instances in a project.

    Args:
        project: GCP project ID

    Returns:
        List of CloudSQLInstance objects

    Example:
        >>> instances = list_cloudsql_instances("my-project")
        >>> for inst in instances:
        ...     print(inst.display_name)
    """
    if not check_gcloud_installed():
        return []

    try:
        result = subprocess.run(
            [
                "gcloud", "sql", "instances", "list",
                "--project", project,
                "--format=json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.debug("gcloud sql instances list failed: %s", result.stderr)
            return []

        instances_data = json.loads(result.stdout)
        instances = []

        for inst in instances_data:
            # Only include PostgreSQL instances
            db_version = inst.get("databaseVersion", "")
            if not db_version.startswith("POSTGRES"):
                continue

            name = inst.get("name", "")
            region = inst.get("region", "")
            connection_name = inst.get("connectionName", f"{project}:{region}:{name}")

            instances.append(CloudSQLInstance(
                name=name,
                project=project,
                region=region,
                database_version=db_version,
                state=inst.get("state", "UNKNOWN"),
                connection_name=connection_name,
            ))

        return instances

    except subprocess.TimeoutExpired:
        logger.warning("gcloud sql instances list timed out")
        return []
    except json.JSONDecodeError:
        logger.warning("Failed to parse gcloud sql output")
        return []
    except Exception as e:
        logger.debug("gcloud sql instances list failed: %s", e)
        return []


def check_database_exists(project: str, instance: str, database: str) -> bool:
    """Check if a database exists in a Cloud SQL instance.

    Args:
        project: GCP project ID
        instance: Cloud SQL instance name
        database: Database name to check

    Returns:
        True if database exists

    Example:
        >>> exists = check_database_exists("my-project", "my-instance", "agv")
    """
    if not check_gcloud_installed():
        return False

    try:
        result = subprocess.run(
            [
                "gcloud", "sql", "databases", "list",
                "--project", project,
                "--instance", instance,
                "--format=value(name)",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode == 0:
            databases = result.stdout.strip().split("\n")
            return database in databases

        return False

    except Exception as e:
        logger.debug("gcloud sql databases list failed: %s", e)
        return False


def create_database(project: str, instance: str, database: str) -> tuple[bool, str]:
    """Create a database in a Cloud SQL instance.

    Args:
        project: GCP project ID
        instance: Cloud SQL instance name
        database: Database name to create

    Returns:
        Tuple of (success, message)

    Example:
        >>> success, msg = create_database("my-project", "my-instance", "agv")
    """
    if not check_gcloud_installed():
        return False, "gcloud CLI not available"

    try:
        result = subprocess.run(
            [
                "gcloud", "sql", "databases", "create", database,
                "--project", project,
                "--instance", instance,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0:
            return True, f"Database '{database}' created"

        # Check for common errors
        stderr = result.stderr
        if "already exists" in stderr.lower():
            return True, f"Database '{database}' already exists"

        return False, f"Failed to create database: {stderr}"

    except subprocess.TimeoutExpired:
        return False, "Database creation timed out"
    except Exception as e:
        return False, f"Failed to create database: {e}"


def list_databases(project: str, instance: str) -> list[str]:
    """List databases in a Cloud SQL instance.

    Args:
        project: GCP project ID
        instance: Cloud SQL instance name

    Returns:
        List of database names

    Example:
        >>> databases = list_databases("my-project", "my-instance")
        >>> for db in databases:
        ...     print(db)
    """
    if not check_gcloud_installed():
        return []

    try:
        result = subprocess.run(
            [
                "gcloud", "sql", "databases", "list",
                "--project", project,
                "--instance", instance,
                "--format=value(name)",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode == 0:
            return [db.strip() for db in result.stdout.strip().split("\n") if db.strip()]

        return []

    except Exception as e:
        logger.debug("gcloud sql databases list failed: %s", e)
        return []


@dataclass
class AlloyDBCluster:
    """AlloyDB cluster information."""

    name: str
    project: str
    region: str
    state: str

    @property
    def display_name(self) -> str:
        """Display name for user selection."""
        return f"{self.name} ({self.region}, {self.state})"


@dataclass
class AlloyDBInstance:
    """AlloyDB instance information."""

    name: str
    cluster: str
    project: str
    region: str
    instance_type: str
    state: str

    @property
    def display_name(self) -> str:
        """Display name for user selection."""
        return f"{self.name} ({self.instance_type}, {self.state})"


def list_alloydb_clusters(project: str) -> list[AlloyDBCluster]:
    """List AlloyDB clusters in a project.

    Args:
        project: GCP project ID

    Returns:
        List of AlloyDBCluster objects
    """
    if not check_gcloud_installed():
        return []

    try:
        result = subprocess.run(
            [
                "gcloud", "alloydb", "clusters", "list",
                "--project", project,
                "--format=json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.debug("gcloud alloydb clusters list failed: %s", result.stderr)
            return []

        clusters_data = json.loads(result.stdout)
        clusters = []

        for cluster in clusters_data:
            name = cluster.get("name", "").split("/")[-1]
            # Extract region from name path: projects/.../locations/REGION/clusters/NAME
            parts = cluster.get("name", "").split("/")
            region = parts[3] if len(parts) > 3 else ""

            clusters.append(AlloyDBCluster(
                name=name,
                project=project,
                region=region,
                state=cluster.get("state", "UNKNOWN"),
            ))

        return clusters

    except subprocess.TimeoutExpired:
        logger.warning("gcloud alloydb clusters list timed out")
        return []
    except json.JSONDecodeError:
        logger.warning("Failed to parse gcloud alloydb output")
        return []
    except Exception as e:
        logger.debug("gcloud alloydb clusters list failed: %s", e)
        return []


def list_alloydb_instances(
    project: str, region: str, cluster: str
) -> list[AlloyDBInstance]:
    """List AlloyDB instances in a cluster.

    Args:
        project: GCP project ID
        region: GCP region
        cluster: AlloyDB cluster name

    Returns:
        List of AlloyDBInstance objects
    """
    if not check_gcloud_installed():
        return []

    try:
        result = subprocess.run(
            [
                "gcloud", "alloydb", "instances", "list",
                "--project", project,
                "--region", region,
                "--cluster", cluster,
                "--format=json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.debug("gcloud alloydb instances list failed: %s", result.stderr)
            return []

        instances_data = json.loads(result.stdout)
        instances = []

        for inst in instances_data:
            name = inst.get("name", "").split("/")[-1]

            instances.append(AlloyDBInstance(
                name=name,
                cluster=cluster,
                project=project,
                region=region,
                instance_type=inst.get("instanceType", "UNKNOWN"),
                state=inst.get("state", "UNKNOWN"),
            ))

        return instances

    except subprocess.TimeoutExpired:
        logger.warning("gcloud alloydb instances list timed out")
        return []
    except json.JSONDecodeError:
        logger.warning("Failed to parse gcloud alloydb instances output")
        return []
    except Exception as e:
        logger.debug("gcloud alloydb instances list failed: %s", e)
        return []


def check_adc_configured() -> tuple[bool, str]:
    """Check if Application Default Credentials are configured.

    Returns:
        Tuple of (configured, message)

    Example:
        >>> configured, msg = check_adc_configured()
        >>> if not configured:
        ...     print(f"ADC not configured: {msg}")
    """
    if not check_gcloud_installed():
        return False, "gcloud CLI not installed"

    try:
        # Try to print ADC to check if configured
        result = subprocess.run(
            ["gcloud", "auth", "application-default", "print-access-token"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            return True, "ADC configured"

        stderr = result.stderr.lower()
        if "not found" in stderr or "could not find" in stderr:
            return False, (
                "ADC not configured. Run:\n"
                "  gcloud auth application-default login"
            )

        return False, "ADC check failed"

    except subprocess.TimeoutExpired:
        return False, "ADC check timed out"
    except Exception as e:
        return False, f"ADC check failed: {e}"


def get_iam_email(project: str) -> Optional[str]:
    """Get the IAM email for the current authenticated user.

    Args:
        project: GCP project ID (for service account formatting)

    Returns:
        IAM email address suitable for Cloud SQL, or None

    Example:
        >>> email = get_iam_email("my-project")
        >>> print(f"IAM user: {email}")
    """
    auth_info = check_gcloud_auth()
    if not auth_info:
        return None

    # For service accounts, return as-is
    if auth_info.is_service_account:
        return auth_info.account

    # For user accounts, return as-is (Cloud SQL supports user@domain.com)
    return auth_info.account
