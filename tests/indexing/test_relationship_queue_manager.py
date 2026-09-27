"""Unit tests for RelationshipQueueManager."""

import pytest

pytestmark = pytest.mark.unit

from unittest.mock import MagicMock

from agentic_inquiry.indexing.relationship_queue_manager import RelationshipQueueManager


def create_mock_relationship(
    source_name: str = "source",
    target_name: str = "target",
    rel_type: str = "calls",
    source_type: str = "function",
    target_type: str = "function",
) -> MagicMock:
    """Create a mock ParserRelationship."""
    rel = MagicMock()
    rel.source_name = source_name
    rel.target_name = target_name
    rel.type = rel_type
    rel.source_type = source_type
    rel.target_type = target_type
    return rel


class TestRelationshipQueueManagerInit:
    """Tests for RelationshipQueueManager initialization."""

    def test_init_creates_empty_queues(self):
        """Test that initialization creates empty queues."""
        manager = RelationshipQueueManager()
        assert manager.pending_count == 0
        assert manager.committed_count == 0

    def test_get_pending_relationships_empty(self):
        """Test getting pending relationships when empty."""
        manager = RelationshipQueueManager()
        assert manager.get_pending_relationships() == []


class TestAddPendingRelationship:
    """Tests for adding relationships to the queue."""

    def test_add_single_relationship(self):
        """Test adding a single relationship."""
        manager = RelationshipQueueManager()
        rel = create_mock_relationship()

        manager.add_pending_relationship(rel, "/path/to/file.py")

        assert manager.pending_count == 1

    def test_add_multiple_relationships(self):
        """Test adding multiple relationships."""
        manager = RelationshipQueueManager()

        for i in range(5):
            rel = create_mock_relationship(source_name=f"source_{i}")
            manager.add_pending_relationship(rel, f"/path/to/file_{i}.py")

        assert manager.pending_count == 5

    def test_add_duplicate_relationships_allowed(self):
        """Test that duplicate relationships are allowed in the queue."""
        manager = RelationshipQueueManager()
        rel = create_mock_relationship()

        # Add same relationship twice
        manager.add_pending_relationship(rel, "/path/to/file.py")
        manager.add_pending_relationship(rel, "/path/to/file.py")

        # Both should be in queue (deduplication happens during filtering)
        assert manager.pending_count == 2

    def test_get_pending_relationships_returns_copy(self):
        """Test that get_pending_relationships returns a copy."""
        manager = RelationshipQueueManager()
        rel = create_mock_relationship()
        manager.add_pending_relationship(rel, "/path/to/file.py")

        pending = manager.get_pending_relationships()
        pending.clear()  # Modify the returned list

        # Original should be unchanged
        assert manager.pending_count == 1


class TestClearOperations:
    """Tests for clearing queues."""

    def test_clear_pending_relationships(self):
        """Test clearing pending relationships."""
        manager = RelationshipQueueManager()
        for i in range(3):
            rel = create_mock_relationship(source_name=f"source_{i}")
            manager.add_pending_relationship(rel, f"/path/to/file_{i}.py")

        assert manager.pending_count == 3
        manager.clear_pending_relationships()
        assert manager.pending_count == 0

    def test_clear_committed_relationship_ids(self):
        """Test clearing committed relationship IDs."""
        manager = RelationshipQueueManager()
        rel = create_mock_relationship()

        # Mark a relationship as committed
        manager.mark_relationships_committed([(rel, "/path/to/file.py")])
        assert manager.committed_count == 1

        manager.clear_committed_relationship_ids()
        assert manager.committed_count == 0


class TestGenerateRelationshipId:
    """Tests for relationship ID generation."""

    def test_generate_relationship_id_deterministic(self):
        """Test that ID generation is deterministic."""
        rel = create_mock_relationship()

        id1 = RelationshipQueueManager.generate_relationship_id(rel, "/path/to/file.py")
        id2 = RelationshipQueueManager.generate_relationship_id(rel, "/path/to/file.py")

        assert id1 == id2

    def test_generate_relationship_id_different_for_different_inputs(self):
        """Test that different inputs produce different IDs."""
        rel1 = create_mock_relationship(source_name="source1")
        rel2 = create_mock_relationship(source_name="source2")

        id1 = RelationshipQueueManager.generate_relationship_id(
            rel1, "/path/to/file.py"
        )
        id2 = RelationshipQueueManager.generate_relationship_id(
            rel2, "/path/to/file.py"
        )

        assert id1 != id2

    def test_generate_relationship_id_different_for_different_files(self):
        """Test that same relationship in different files produces different IDs."""
        rel = create_mock_relationship()

        id1 = RelationshipQueueManager.generate_relationship_id(
            rel, "/path/to/file1.py"
        )
        id2 = RelationshipQueueManager.generate_relationship_id(
            rel, "/path/to/file2.py"
        )

        assert id1 != id2

    def test_generate_relationship_id_format(self):
        """Test that generated ID has expected format."""
        rel = create_mock_relationship()

        rel_id = RelationshipQueueManager.generate_relationship_id(
            rel, "/path/to/file.py"
        )

        # Should be a 16-character hex string (SHA256 truncated)
        assert len(rel_id) == 16
        assert all(c in "0123456789abcdef" for c in rel_id)


class TestFilterUncommittedRelationships:
    """Tests for filtering uncommitted relationships."""

    def test_filter_all_uncommitted(self):
        """Test filtering when all relationships are uncommitted."""
        manager = RelationshipQueueManager()

        relationships = [
            (create_mock_relationship(source_name=f"source_{i}"), f"/path/file_{i}.py")
            for i in range(5)
        ]

        uncommitted, skipped = manager.filter_uncommitted_relationships(relationships)

        assert len(uncommitted) == 5
        assert skipped == 0

    def test_filter_all_committed(self):
        """Test filtering when all relationships are committed."""
        manager = RelationshipQueueManager()

        relationships = [
            (create_mock_relationship(source_name=f"source_{i}"), f"/path/file_{i}.py")
            for i in range(5)
        ]

        # Mark all as committed
        manager.mark_relationships_committed(relationships)

        uncommitted, skipped = manager.filter_uncommitted_relationships(relationships)

        assert len(uncommitted) == 0
        assert skipped == 5

    def test_filter_mixed_committed_uncommitted(self):
        """Test filtering when some relationships are committed."""
        manager = RelationshipQueueManager()

        relationships = [
            (create_mock_relationship(source_name=f"source_{i}"), f"/path/file_{i}.py")
            for i in range(5)
        ]

        # Mark only first 2 as committed
        manager.mark_relationships_committed(relationships[:2])

        uncommitted, skipped = manager.filter_uncommitted_relationships(relationships)

        assert len(uncommitted) == 3
        assert skipped == 2

    def test_filter_empty_list(self):
        """Test filtering an empty list."""
        manager = RelationshipQueueManager()

        uncommitted, skipped = manager.filter_uncommitted_relationships([])

        assert uncommitted == []
        assert skipped == 0


class TestMarkRelationshipsCommitted:
    """Tests for marking relationships as committed."""

    def test_mark_single_relationship_committed(self):
        """Test marking a single relationship as committed."""
        manager = RelationshipQueueManager()
        rel = create_mock_relationship()

        manager.mark_relationships_committed([(rel, "/path/to/file.py")])

        assert manager.committed_count == 1
        assert manager.is_relationship_committed(rel, "/path/to/file.py")

    def test_mark_multiple_relationships_committed(self):
        """Test marking multiple relationships as committed."""
        manager = RelationshipQueueManager()

        relationships = [
            (create_mock_relationship(source_name=f"source_{i}"), f"/path/file_{i}.py")
            for i in range(5)
        ]

        manager.mark_relationships_committed(relationships)

        assert manager.committed_count == 5
        for rel, path in relationships:
            assert manager.is_relationship_committed(rel, path)

    def test_mark_same_relationship_twice(self):
        """Test that marking the same relationship twice doesn't duplicate."""
        manager = RelationshipQueueManager()
        rel = create_mock_relationship()

        manager.mark_relationships_committed([(rel, "/path/to/file.py")])
        manager.mark_relationships_committed([(rel, "/path/to/file.py")])

        # Should only be counted once (set behavior)
        assert manager.committed_count == 1


class TestRemovePendingRelationshipsForFile:
    """Tests for removing relationships by file path."""

    def test_remove_relationships_for_single_file(self):
        """Test removing relationships for a specific file."""
        manager = RelationshipQueueManager()

        # Add relationships for different files
        manager.add_pending_relationship(
            create_mock_relationship(source_name="s1"), "/path/file1.py"
        )
        manager.add_pending_relationship(
            create_mock_relationship(source_name="s2"), "/path/file1.py"
        )
        manager.add_pending_relationship(
            create_mock_relationship(source_name="s3"), "/path/file2.py"
        )

        removed = manager.remove_pending_relationships_for_file("/path/file1.py")

        assert removed == 2
        assert manager.pending_count == 1

    def test_remove_relationships_for_nonexistent_file(self):
        """Test removing relationships for a file that has none."""
        manager = RelationshipQueueManager()
        manager.add_pending_relationship(create_mock_relationship(), "/path/file1.py")

        removed = manager.remove_pending_relationships_for_file("/path/file2.py")

        assert removed == 0
        assert manager.pending_count == 1

    def test_remove_all_relationships(self):
        """Test removing all relationships for the only file."""
        manager = RelationshipQueueManager()

        for i in range(3):
            manager.add_pending_relationship(
                create_mock_relationship(source_name=f"s{i}"), "/path/file.py"
            )

        removed = manager.remove_pending_relationships_for_file("/path/file.py")

        assert removed == 3
        assert manager.pending_count == 0


class TestIsRelationshipCommitted:
    """Tests for checking if a relationship is committed."""

    def test_uncommitted_relationship(self):
        """Test that uncommitted relationship returns False."""
        manager = RelationshipQueueManager()
        rel = create_mock_relationship()

        assert not manager.is_relationship_committed(rel, "/path/to/file.py")

    def test_committed_relationship(self):
        """Test that committed relationship returns True."""
        manager = RelationshipQueueManager()
        rel = create_mock_relationship()

        manager.mark_relationships_committed([(rel, "/path/to/file.py")])

        assert manager.is_relationship_committed(rel, "/path/to/file.py")

    def test_same_relationship_different_file(self):
        """Test that same relationship in different file is not committed."""
        manager = RelationshipQueueManager()
        rel = create_mock_relationship()

        manager.mark_relationships_committed([(rel, "/path/file1.py")])

        assert manager.is_relationship_committed(rel, "/path/file1.py")
        assert not manager.is_relationship_committed(rel, "/path/file2.py")


class TestGetStats:
    """Tests for getting statistics."""

    def test_stats_empty(self):
        """Test stats when empty."""
        manager = RelationshipQueueManager()

        stats = manager.get_stats()

        assert stats["pending_count"] == 0
        assert stats["committed_count"] == 0

    def test_stats_with_data(self):
        """Test stats with pending and committed relationships."""
        manager = RelationshipQueueManager()

        # Add pending relationships
        for i in range(3):
            manager.add_pending_relationship(
                create_mock_relationship(source_name=f"s{i}"), f"/path/file_{i}.py"
            )

        # Mark some as committed
        manager.mark_relationships_committed(
            [
                (create_mock_relationship(source_name="committed1"), "/path/c1.py"),
                (create_mock_relationship(source_name="committed2"), "/path/c2.py"),
            ]
        )

        stats = manager.get_stats()

        assert stats["pending_count"] == 3
        assert stats["committed_count"] == 2


class TestCleanupProcessedBatch:
    """Tests for cleanup_processed_batch method."""

    def test_cleanup_empty_list(self):
        """Test cleanup with empty processed list."""
        manager = RelationshipQueueManager()

        # Add some pending relationships
        for i in range(3):
            manager.add_pending_relationship(
                create_mock_relationship(source_name=f"s{i}"), f"/path/file_{i}.py"
            )

        removed = manager.cleanup_processed_batch([])

        assert removed == 0
        assert manager.pending_count == 3

    def test_cleanup_removes_processed_relationships(self):
        """Test that processed relationships are removed from pending queue."""
        manager = RelationshipQueueManager()

        # Add some pending relationships
        rel1 = create_mock_relationship(source_name="s1")
        rel2 = create_mock_relationship(source_name="s2")
        rel3 = create_mock_relationship(source_name="s3")

        manager.add_pending_relationship(rel1, "/path/file1.py")
        manager.add_pending_relationship(rel2, "/path/file2.py")
        manager.add_pending_relationship(rel3, "/path/file3.py")

        # Cleanup only the first two
        processed = [(rel1, "/path/file1.py"), (rel2, "/path/file2.py")]
        removed = manager.cleanup_processed_batch(processed)

        assert removed == 2
        assert manager.pending_count == 1

    def test_cleanup_non_matching_relationships(self):
        """Test cleanup with relationships not in pending queue."""
        manager = RelationshipQueueManager()

        # Add some pending relationships
        manager.add_pending_relationship(
            create_mock_relationship(source_name="s1"), "/path/file1.py"
        )

        # Try to cleanup a different relationship
        other_rel = create_mock_relationship(source_name="other")
        removed = manager.cleanup_processed_batch([(other_rel, "/path/other.py")])

        assert removed == 0
        assert manager.pending_count == 1

    def test_cleanup_all_pending_relationships(self):
        """Test cleanup of all pending relationships."""
        manager = RelationshipQueueManager()

        # Add some pending relationships
        relationships = []
        for i in range(5):
            rel = create_mock_relationship(source_name=f"s{i}")
            path = f"/path/file_{i}.py"
            manager.add_pending_relationship(rel, path)
            relationships.append((rel, path))

        # Cleanup all
        removed = manager.cleanup_processed_batch(relationships)

        assert removed == 5
        assert manager.pending_count == 0
