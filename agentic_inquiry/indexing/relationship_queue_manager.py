"""Relationship queue management for graph construction.

This module handles the queuing and tracking of relationships during
graph building operations. It provides idempotent resume capability
by tracking committed relationships.
"""

import hashlib
import logging
from typing import Any, Dict, List, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from agentic_inquiry.parsers.models import ParserRelationship

logger = logging.getLogger(__name__)


class RelationshipQueueManager:
    """Manages relationship queuing and commit tracking.

    This class handles the pending relationships queue and tracks which
    relationships have been committed to enable idempotent resume after
    interruption.

    Responsibilities:
    - Queue relationships for batch processing
    - Track committed relationships for deduplication
    - Filter uncommitted relationships for resume
    - Remove relationships by file path

    Args:
        None - this is a stateful queue manager
    """

    def __init__(self) -> None:
        # Pending relationships to be processed: (ParserRelationship, source_file_path)
        self._pending_relationships: List[Tuple["ParserRelationship", str]] = []

        # Track committed relationships for resume/deduplication
        # This enables idempotent resume after interruption
        self._committed_relationship_ids: Set[str] = set()

    @property
    def pending_count(self) -> int:
        """Return the number of pending relationships."""
        return len(self._pending_relationships)

    @property
    def committed_count(self) -> int:
        """Return the number of committed relationship IDs."""
        return len(self._committed_relationship_ids)

    def get_pending_relationships(self) -> List[Tuple["ParserRelationship", str]]:
        """Get a copy of pending relationships.

        Returns:
            List of (ParserRelationship, source_file_path) tuples
        """
        return list(self._pending_relationships)

    @staticmethod
    def generate_relationship_id(
        relationship: "ParserRelationship", source_file_path: str
    ) -> str:
        """Generate a unique ID for a relationship for deduplication.

        The ID is based on the relationship's key attributes to enable
        idempotent resume after interruption.

        Args:
            relationship: The relationship to generate an ID for
            source_file_path: Path to the source file

        Returns:
            A unique identifier string for this relationship
        """
        # Create a deterministic ID from relationship attributes
        # ParserRelationship uses: source_name, target_name, type
        id_parts = [
            source_file_path,
            relationship.source_name,
            relationship.target_name,
            relationship.type,
            relationship.source_type,
            relationship.target_type,
        ]
        id_string = "|".join(id_parts)
        return hashlib.sha256(id_string.encode()).hexdigest()[:16]

    def add_pending_relationship(
        self, relationship: "ParserRelationship", source_file_path: str
    ) -> None:
        """Add a relationship to the pending queue for later resolution.

        Args:
            relationship: The relationship to add
            source_file_path: Path to the source file
        """
        self._pending_relationships.append((relationship, source_file_path))

    def clear_pending_relationships(self) -> None:
        """Clear all pending relationships."""
        self._pending_relationships.clear()

    def clear_committed_relationship_ids(self) -> None:
        """Clear the set of committed relationship IDs.

        Call this when starting a fresh flush operation that should not
        consider previous commits for deduplication.
        """
        self._committed_relationship_ids.clear()

    def filter_uncommitted_relationships(
        self,
        relationships: List[Tuple["ParserRelationship", str]],
    ) -> Tuple[List[Tuple["ParserRelationship", str]], int]:
        """Filter out relationships that have already been committed.

        This enables idempotent resume after interruption by skipping
        relationships that were already processed and committed.

        Args:
            relationships: List of (relationship, source_file_path) tuples

        Returns:
            Tuple of (filtered_relationships, skipped_count)
        """
        uncommitted = []
        skipped = 0

        for rel, source_path in relationships:
            rel_id = self.generate_relationship_id(rel, source_path)
            if rel_id not in self._committed_relationship_ids:
                uncommitted.append((rel, source_path))
            else:
                skipped += 1

        return uncommitted, skipped

    def mark_relationships_committed(
        self,
        relationships: List[Tuple["ParserRelationship", str]],
    ) -> None:
        """Mark relationships as committed for deduplication.

        Args:
            relationships: List of (relationship, source_file_path) tuples
        """
        for rel, source_path in relationships:
            rel_id = self.generate_relationship_id(rel, source_path)
            self._committed_relationship_ids.add(rel_id)

    def remove_pending_relationships_for_file(self, file_path: str) -> int:
        """Remove pending relationships for a specific file.

        Args:
            file_path: Path to the file whose relationships should be removed

        Returns:
            Number of relationships removed
        """
        original_count = len(self._pending_relationships)
        self._pending_relationships = [
            (rel, source_file)
            for rel, source_file in self._pending_relationships
            if source_file != file_path
        ]
        removed_count = original_count - len(self._pending_relationships)

        if removed_count > 0:
            logger.debug(
                "Removed %d pending relationships for file: %s",
                removed_count,
                file_path,
            )

        return removed_count

    def cleanup_processed_batch(
        self,
        processed_relationships: List[Tuple["ParserRelationship", str]],
    ) -> int:
        """Clean up processed relationships from pending queue.

        This frees memory by removing relationships that have been successfully
        processed and committed.

        Args:
            processed_relationships: List of (relationship, source_file_path) tuples
                that were processed

        Returns:
            Number of relationships removed from the pending queue
        """
        if not processed_relationships:
            return 0

        # Create set of processed relationship IDs for efficient lookup
        processed_ids = {
            self.generate_relationship_id(rel, source_path)
            for rel, source_path in processed_relationships
        }

        original_count = len(self._pending_relationships)

        # Remove processed relationships from pending queue
        self._pending_relationships = [
            (rel, source_path)
            for rel, source_path in self._pending_relationships
            if self.generate_relationship_id(rel, source_path) not in processed_ids
        ]

        removed = original_count - len(self._pending_relationships)

        if removed > 0:
            logger.debug(
                "Cleaned up %d processed relationships from pending queue",
                removed,
            )

        return removed

    def is_relationship_committed(
        self, relationship: "ParserRelationship", source_file_path: str
    ) -> bool:
        """Check if a specific relationship has been committed.

        Args:
            relationship: The relationship to check
            source_file_path: Path to the source file

        Returns:
            True if the relationship has been committed, False otherwise
        """
        rel_id = self.generate_relationship_id(relationship, source_file_path)
        return rel_id in self._committed_relationship_ids

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the queue state.

        Returns:
            Dictionary with pending_count, committed_count
        """
        return {
            "pending_count": self.pending_count,
            "committed_count": self.committed_count,
        }
