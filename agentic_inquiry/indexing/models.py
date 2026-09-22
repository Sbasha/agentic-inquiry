"""Data models for indexing operations."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class IndexingError:
    """Error that occurred during indexing with context.
    
    Attributes:
        file_path: Path to the file that failed
        error_type: Type of error (e.g., "ParseError", "SchemaValidationError")
        error_message: Detailed error message
        suggestion: Suggested remediation for the error
    """
    file_path: str
    error_type: str
    error_message: str
    suggestion: str
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation of the error
        """
        return {
            "file": self.file_path,
            "error": self.error_type,
            "message": self.error_message,
            "suggestion": self.suggestion
        }


@dataclass
class IndexingResult:
    """Result of an indexing operation.

    Attributes:
        operation_id: Unique identifier for the operation
        status: Operation status. One of:
            - "completed": All files processed successfully
            - "completed_with_errors": Some files succeeded, some failed
            - "no_files_found": No indexable files found in directory
            - "all_files_failed": All files failed to process
            - "partial_failure": Processed 0 files due to errors
            - "failed": Operation failed entirely
            - "in_progress": Operation still running
        chunks_created: Number of chunks created
        entities_created: Number of entities created
        relationships_created: Number of relationships created (default 0)
        files_processed: Number of files successfully processed
        files_failed: Number of files that failed to process
        errors: List of errors that occurred during indexing
        message: Human-readable message about the operation
        diagnostics: Optional dictionary with debugging information
    """
    operation_id: str
    status: str
    chunks_created: int = 0
    entities_created: int = 0
    relationships_created: int = 0
    files_processed: int = 0
    files_failed: int = 0
    errors: list[IndexingError] = field(default_factory=list)
    message: str = ""
    diagnostics: Optional[dict[str, Any]] = None
    
    def is_empty(self) -> bool:
        """Check if indexing created no data.

        Returns:
            True if no chunks or entities were created
        """
        return self.chunks_created == 0 and self.entities_created == 0

    def is_partial_success(self) -> bool:
        """Check if some files succeeded but others failed.

        Returns:
            True if at least one file succeeded and at least one failed
        """
        return self.files_processed > 0 and self.files_failed > 0

    def is_success(self) -> bool:
        """Check if indexing completed successfully.

        Returns:
            True if status indicates successful completion
        """
        return self.status in ("completed", "completed_with_errors")

    def is_empty_result(self) -> bool:
        """Check if no files were indexed.

        Returns:
            True if no files were processed
        """
        return self.files_processed == 0

    def has_graph_data(self) -> bool:
        """Check if any graph data was created.

        Returns:
            True if any entities or relationships were created
        """
        return self.entities_created > 0 or self.relationships_created > 0

    @property
    def files_discovered(self) -> int:
        """Get count of files discovered (from diagnostics).

        Returns:
            Number of files discovered, or sum of processed + failed if unavailable
        """
        if self.diagnostics:
            return self.diagnostics.get("files_discovered", 0)
        return self.files_processed + self.files_failed

    def to_dict(self) -> dict:
        """Convert to dictionary for MCP response serialization.

        Returns:
            Dictionary representation suitable for JSON serialization
        """
        result = {
            "operation_id": self.operation_id,
            "status": self.status,
            "chunks_created": self.chunks_created,
            "entities_created": self.entities_created,
            "relationships_created": self.relationships_created,
            "files_processed": self.files_processed,
            "files_failed": self.files_failed,
            "errors": [error.to_dict() for error in self.errors],
            "message": self.message,
        }
        if self.diagnostics:
            result["diagnostics"] = self.diagnostics
        return result


__all__ = ["IndexingError", "IndexingResult"]
