"""Audit logging for schema changes and sensitive operations.

This module provides structured audit logging for schema migrations,
backup operations, and other sensitive database operations.

Design principles:
    - Structured logging with consistent format
    - Security-focused (SEC-2 requirement)
    - Includes timestamp, operation, user, table, before/after state
    - Easy to parse for compliance audits

Usage:
    >>> from agent_vault.storage.audit import audit_logger, AuditEvent
    >>>
    >>> audit_logger.log_migration_start(
    ...     table_name="chunks_table",
    ...     old_dimension=768,
    ...     new_dimension=1536,
    ...     user="admin@example.com"
    ... )
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Optional

# Configure audit logger (separate from application logger)
audit_logger = logging.getLogger("agent_vault.audit")
audit_logger.setLevel(logging.INFO)

# Ensure audit logs go to a separate handler if configured
# (Users can configure this in their logging setup)


class AuditEventType(Enum):
    """Types of auditable events."""

    MIGRATION_START = "migration_start"
    MIGRATION_SUCCESS = "migration_success"
    MIGRATION_FAILURE = "migration_failure"
    BACKUP_CREATE = "backup_create"
    BACKUP_VERIFY = "backup_verify"
    BACKUP_RESTORE = "backup_restore"
    BACKUP_DELETE = "backup_delete"
    RESTORE_START = "restore_start"
    RESTORE_SUCCESS = "restore_success"
    RESTORE_FAILURE = "restore_failure"
    INDEX_REBUILD = "index_rebuild"
    SCHEMA_ALTER = "schema_alter"


class AuditEvent:
    """Structured audit event for schema changes."""

    def __init__(
        self,
        event_type: AuditEventType,
        table_name: str,
        user: Optional[str] = None,
        operation: Optional[str] = None,
        before_state: Optional[dict[str, Any]] = None,
        after_state: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        """Create an audit event.

        Args:
            event_type: Type of audit event
            table_name: Name of the table affected
            user: User or service account performing the operation
            operation: Description of the operation (e.g., "ALTER TABLE", "CREATE BACKUP")
            before_state: State before the operation (e.g., {"dimension": 768})
            after_state: State after the operation (e.g., {"dimension": 1536})
            metadata: Additional context (e.g., {"backup_table": "...", "row_count": 1000})
        """
        self.timestamp = datetime.utcnow().isoformat()
        self.event_type = event_type
        self.table_name = table_name
        self.user = user or "unknown"
        self.operation = operation
        self.before_state = before_state or {}
        self.after_state = after_state or {}
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for logging."""
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "table_name": self.table_name,
            "user": self.user,
            "operation": self.operation,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "metadata": self.metadata,
        }

    def __str__(self) -> str:
        """Format event as structured log line."""
        parts = [
            f"[{self.timestamp}]",
            f"event={self.event_type.value}",
            f"table={self.table_name}",
            f"user={self.user}",
        ]

        if self.operation:
            parts.append(f"operation={self.operation}")

        if self.before_state:
            parts.append(f"before={self.before_state}")

        if self.after_state:
            parts.append(f"after={self.after_state}")

        if self.metadata:
            parts.append(f"metadata={self.metadata}")

        return " ".join(parts)


class SchemaAuditLogger:
    """Audit logger for schema changes and migrations."""

    def __init__(self, logger: logging.Logger = audit_logger):
        """Initialize audit logger.

        Args:
            logger: Logger instance to use (defaults to module audit_logger)
        """
        self.logger = logger

    def log_event(self, event: AuditEvent) -> None:
        """Log an audit event.

        Args:
            event: The audit event to log
        """
        self.logger.info(str(event), extra=event.to_dict())

    def log_migration_start(
        self,
        table_name: str,
        old_dimension: int,
        new_dimension: int,
        user: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log the start of a schema migration.

        Args:
            table_name: Name of the table being migrated
            old_dimension: Current embedding dimension
            new_dimension: Target embedding dimension
            user: User or service account performing migration
            metadata: Additional context (e.g., backup_table, row_count)
        """
        event = AuditEvent(
            event_type=AuditEventType.MIGRATION_START,
            table_name=table_name,
            user=user,
            operation="MIGRATE_DIMENSION",
            before_state={"dimension": old_dimension},
            after_state={"dimension": new_dimension},
            metadata=metadata,
        )
        self.log_event(event)

    def log_migration_success(
        self,
        table_name: str,
        old_dimension: int,
        new_dimension: int,
        duration_seconds: float,
        user: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log successful completion of a schema migration.

        Args:
            table_name: Name of the table migrated
            old_dimension: Original embedding dimension
            new_dimension: New embedding dimension
            duration_seconds: Time taken for migration
            user: User or service account that performed migration
            metadata: Additional context (e.g., rows_affected, backup_table)
        """
        meta = metadata or {}
        meta["duration_seconds"] = duration_seconds

        event = AuditEvent(
            event_type=AuditEventType.MIGRATION_SUCCESS,
            table_name=table_name,
            user=user,
            operation="MIGRATE_DIMENSION",
            before_state={"dimension": old_dimension},
            after_state={"dimension": new_dimension},
            metadata=meta,
        )
        self.log_event(event)

    def log_migration_failure(
        self,
        table_name: str,
        error: str,
        user: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log failed schema migration.

        Args:
            table_name: Name of the table being migrated
            error: Error message describing the failure
            user: User or service account that attempted migration
            metadata: Additional context (e.g., backup_table, step_failed)
        """
        meta = metadata or {}
        meta["error"] = error

        event = AuditEvent(
            event_type=AuditEventType.MIGRATION_FAILURE,
            table_name=table_name,
            user=user,
            operation="MIGRATE_DIMENSION",
            metadata=meta,
        )
        self.log_event(event)

    def log_backup_create(
        self,
        table_name: str,
        backup_table: str,
        row_count: int,
        user: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log creation of a backup table.

        Args:
            table_name: Name of the source table
            backup_table: Name of the backup table created
            row_count: Number of rows backed up
            user: User or service account that created backup
            metadata: Additional context (e.g., retention_days, size_bytes)
        """
        meta = metadata or {}
        meta["backup_table"] = backup_table
        meta["row_count"] = row_count

        event = AuditEvent(
            event_type=AuditEventType.BACKUP_CREATE,
            table_name=table_name,
            user=user,
            operation="CREATE_BACKUP",
            metadata=meta,
        )
        self.log_event(event)

    def log_backup_verify(
        self,
        table_name: str,
        backup_table: str,
        source_count: int,
        backup_count: int,
        verified: bool,
        user: Optional[str] = None,
    ) -> None:
        """Log backup verification result.

        Args:
            table_name: Name of the source table
            backup_table: Name of the backup table
            source_count: Row count in source table
            backup_count: Row count in backup table
            verified: Whether counts match (verification passed)
            user: User or service account performing verification
        """
        event = AuditEvent(
            event_type=AuditEventType.BACKUP_VERIFY,
            table_name=table_name,
            user=user,
            operation="VERIFY_BACKUP",
            metadata={
                "backup_table": backup_table,
                "source_count": source_count,
                "backup_count": backup_count,
                "verified": verified,
            },
        )
        self.log_event(event)

    def log_restore_start(
        self,
        table_name: str,
        backup_table: str,
        user: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log the start of a backup restore operation.

        Args:
            table_name: Name of the table being restored
            backup_table: Name of the backup table to restore from
            user: User or service account performing restore
            metadata: Additional context
        """
        meta = metadata or {}
        meta["backup_table"] = backup_table

        event = AuditEvent(
            event_type=AuditEventType.RESTORE_START,
            table_name=table_name,
            user=user,
            operation="RESTORE_FROM_BACKUP",
            metadata=meta,
        )
        self.log_event(event)

    def log_restore_success(
        self,
        table_name: str,
        backup_table: str,
        duration_seconds: float,
        user: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log successful completion of a restore operation.

        Args:
            table_name: Name of the table restored
            backup_table: Name of the backup table used
            duration_seconds: Time taken for restore
            user: User or service account that performed restore
            metadata: Additional context (e.g., rows_restored)
        """
        meta = metadata or {}
        meta["backup_table"] = backup_table
        meta["duration_seconds"] = duration_seconds

        event = AuditEvent(
            event_type=AuditEventType.RESTORE_SUCCESS,
            table_name=table_name,
            user=user,
            operation="RESTORE_FROM_BACKUP",
            metadata=meta,
        )
        self.log_event(event)

    def log_restore_failure(
        self,
        table_name: str,
        backup_table: str,
        error: str,
        user: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log failed restore operation.

        Args:
            table_name: Name of the table being restored
            backup_table: Name of the backup table
            error: Error message describing the failure
            user: User or service account that attempted restore
            metadata: Additional context
        """
        meta = metadata or {}
        meta["backup_table"] = backup_table
        meta["error"] = error

        event = AuditEvent(
            event_type=AuditEventType.RESTORE_FAILURE,
            table_name=table_name,
            user=user,
            operation="RESTORE_FROM_BACKUP",
            metadata=meta,
        )
        self.log_event(event)

    def log_index_rebuild(
        self,
        table_name: str,
        index_name: str,
        index_type: str,
        duration_seconds: float,
        user: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log index rebuild operation.

        Args:
            table_name: Name of the table whose index was rebuilt
            index_name: Name of the index
            index_type: Type of index (hnsw, ivfflat)
            duration_seconds: Time taken to rebuild
            user: User or service account that performed rebuild
            metadata: Additional context (e.g., rows_indexed, index_params)
        """
        meta = metadata or {}
        meta["index_name"] = index_name
        meta["index_type"] = index_type
        meta["duration_seconds"] = duration_seconds

        event = AuditEvent(
            event_type=AuditEventType.INDEX_REBUILD,
            table_name=table_name,
            user=user,
            operation="REBUILD_INDEX",
            metadata=meta,
        )
        self.log_event(event)

    def log_backup_restored(
        self,
        table_name: str,
        backup_table: str,
        rows_restored: int,
        user: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log successful backup restore.

        Args:
            table_name: Name of the table restored
            backup_table: Name of the backup table used
            rows_restored: Number of rows restored
            user: User or service account that performed restore
            metadata: Additional context
        """
        meta = metadata or {}
        meta["backup_table"] = backup_table
        meta["rows_restored"] = rows_restored

        event = AuditEvent(
            event_type=AuditEventType.BACKUP_RESTORE,
            table_name=table_name,
            user=user,
            operation="RESTORE_FROM_BACKUP",
            metadata=meta,
        )
        self.log_event(event)

    def log_backup_deleted(
        self,
        backup_table: str,
        reason: str = "manual",
        user: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log backup table deletion.

        Args:
            backup_table: Name of the backup table deleted
            reason: Reason for deletion (e.g., "expired", "manual")
            user: User or service account that performed deletion
            metadata: Additional context
        """
        meta = metadata or {}
        meta["reason"] = reason

        event = AuditEvent(
            event_type=AuditEventType.BACKUP_DELETE,
            table_name=backup_table,
            user=user,
            operation="DELETE_BACKUP",
            metadata=meta,
        )
        self.log_event(event)


# Global audit logger instance
default_audit_logger = SchemaAuditLogger(audit_logger)
