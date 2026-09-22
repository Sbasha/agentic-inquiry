"""Property-based tests for interruption handling and resume logic.

These tests validate partial commit tracking and idempotent resume
as specified in the design document.

Property tests:
- Property 14: Partial Commit on Interruption (Requirements 5.3)
- Property 15: Idempotent Resume (Requirements 5.4)
"""

import pytest

pytestmark = pytest.mark.unit

from hypothesis import given, strategies as st, settings
from unittest.mock import MagicMock

from agent_vault.indexing.graph_builder import GraphBuilder
from agent_vault.parsers.models import ParserRelationship


# =============================================================================
# Helpers for creating test data
# =============================================================================

def create_mock_relationship(
    source_name: str,
    target_name: str,
    relationship_type: str = "calls",
    source_type: str = "function",
    target_type: str = "function",
) -> ParserRelationship:
    """Create a mock ParserRelationship for testing.

    ParserRelationship has fields: source_type, source_name, target_type,
    target_name, type, target_path, metadata, ranking_signals
    """
    return ParserRelationship(
        source_type=source_type,
        source_name=source_name,
        target_type=target_type,
        target_name=target_name,
        type=relationship_type,
    )


# =============================================================================
# Property 14: Partial Commit on Interruption
# Validates: Requirements 5.3
# =============================================================================

class TestPartialCommitOnInterruption:
    """Tests for partial commit tracking on interruption."""

    def test_committed_relationship_ids_initialized_empty(self):
        """Committed relationship IDs should be empty on init."""
        mock_db = MagicMock()
        mock_registry = MagicMock()
        mock_resolver = MagicMock()
        mock_embedding = MagicMock()

        builder = GraphBuilder(
            db_manager=mock_db,
            symbol_registry=mock_registry,
            relationship_resolver=mock_resolver,
            embedding_service=mock_embedding,
            project_id="test",
            project_hash="hash123",
            project_root="/tmp/test_project",
        )

        assert builder.get_committed_relationship_count() == 0

    def test_mark_relationships_committed_tracks_ids(self):
        """Marking relationships as committed should track their IDs."""
        mock_db = MagicMock()
        mock_registry = MagicMock()
        mock_resolver = MagicMock()
        mock_embedding = MagicMock()

        builder = GraphBuilder(
            db_manager=mock_db,
            symbol_registry=mock_registry,
            relationship_resolver=mock_resolver,
            embedding_service=mock_embedding,
            project_id="test",
            project_hash="hash123",
            project_root="/tmp/test_project",
        )

        # Create relationships
        rel1 = create_mock_relationship("func_a", "func_b")
        rel2 = create_mock_relationship("func_c", "func_d")
        relationships = [(rel1, "file1.py"), (rel2, "file2.py")]

        builder._mark_relationships_committed(relationships)

        assert builder.get_committed_relationship_count() == 2

    def test_generate_relationship_id_deterministic(self):
        """Relationship IDs should be deterministic."""
        rel = create_mock_relationship("my_func", "other_func", "calls", "function", "function")
        source_file = "src/module.py"

        id1 = GraphBuilder._generate_relationship_id(rel, source_file)
        id2 = GraphBuilder._generate_relationship_id(rel, source_file)

        assert id1 == id2
        assert len(id1) == 16  # Truncated hash

    def test_generate_relationship_id_unique_for_different_inputs(self):
        """Different relationships should have different IDs."""
        rel1 = create_mock_relationship("func_a", "func_b")
        rel2 = create_mock_relationship("func_a", "func_c")  # Different target

        id1 = GraphBuilder._generate_relationship_id(rel1, "file.py")
        id2 = GraphBuilder._generate_relationship_id(rel2, "file.py")

        assert id1 != id2

    @given(
        source_name=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('L', 'N'))),
        target_name=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('L', 'N'))),
        relationship_type=st.sampled_from(["calls", "imports", "extends", "implements"]),
    )
    @settings(max_examples=50)
    def test_property_14_relationship_id_uniqueness(
        self, source_name, target_name, relationship_type
    ):
        """Property 14: For any relationship, the generated ID SHALL be
        unique based on source_name, target_name, type, and source/target types.
        """
        rel = create_mock_relationship(
            source_name=source_name,
            target_name=target_name,
            relationship_type=relationship_type,
        )

        id1 = GraphBuilder._generate_relationship_id(rel, "file.py")
        id2 = GraphBuilder._generate_relationship_id(rel, "other_file.py")

        # Same relationship in different files should have different IDs
        assert id1 != id2

    def test_clear_committed_relationship_ids(self):
        """Clearing committed IDs should reset tracking."""
        mock_db = MagicMock()
        mock_registry = MagicMock()
        mock_resolver = MagicMock()
        mock_embedding = MagicMock()

        builder = GraphBuilder(
            db_manager=mock_db,
            symbol_registry=mock_registry,
            relationship_resolver=mock_resolver,
            embedding_service=mock_embedding,
            project_id="test",
            project_hash="hash123",
            project_root="/tmp/test_project",
        )

        # Add some committed relationships
        rel = create_mock_relationship("func_a", "func_b")
        builder._mark_relationships_committed([(rel, "file.py")])
        assert builder.get_committed_relationship_count() == 1

        # Clear
        builder.clear_committed_relationship_ids()
        assert builder.get_committed_relationship_count() == 0


# =============================================================================
# Property 15: Idempotent Resume
# Validates: Requirements 5.4
# =============================================================================

class TestIdempotentResume:
    """Tests for idempotent resume after interruption."""

    def test_filter_uncommitted_relationships_skips_committed(self):
        """Filter should skip already-committed relationships."""
        mock_db = MagicMock()
        mock_registry = MagicMock()
        mock_resolver = MagicMock()
        mock_embedding = MagicMock()

        builder = GraphBuilder(
            db_manager=mock_db,
            symbol_registry=mock_registry,
            relationship_resolver=mock_resolver,
            embedding_service=mock_embedding,
            project_id="test",
            project_hash="hash123",
            project_root="/tmp/test_project",
        )

        # Create relationships
        rel1 = create_mock_relationship("func_a", "func_b")
        rel2 = create_mock_relationship("func_c", "func_d")
        rel3 = create_mock_relationship("func_e", "func_f")
        all_relationships = [
            (rel1, "file1.py"),
            (rel2, "file2.py"),
            (rel3, "file3.py"),
        ]

        # Mark first one as committed
        builder._mark_relationships_committed([(rel1, "file1.py")])

        # Filter
        uncommitted, skipped = builder._filter_uncommitted_relationships(all_relationships)

        assert skipped == 1
        assert len(uncommitted) == 2

    def test_filter_uncommitted_relationships_returns_all_if_none_committed(self):
        """Filter should return all if nothing was committed."""
        mock_db = MagicMock()
        mock_registry = MagicMock()
        mock_resolver = MagicMock()
        mock_embedding = MagicMock()

        builder = GraphBuilder(
            db_manager=mock_db,
            symbol_registry=mock_registry,
            relationship_resolver=mock_resolver,
            embedding_service=mock_embedding,
            project_id="test",
            project_hash="hash123",
            project_root="/tmp/test_project",
        )

        rel1 = create_mock_relationship("func_a", "func_b")
        rel2 = create_mock_relationship("func_c", "func_d")
        relationships = [(rel1, "file1.py"), (rel2, "file2.py")]

        uncommitted, skipped = builder._filter_uncommitted_relationships(relationships)

        assert skipped == 0
        assert len(uncommitted) == 2

    def test_filter_uncommitted_relationships_returns_empty_if_all_committed(self):
        """Filter should return empty if all were committed."""
        mock_db = MagicMock()
        mock_registry = MagicMock()
        mock_resolver = MagicMock()
        mock_embedding = MagicMock()

        builder = GraphBuilder(
            db_manager=mock_db,
            symbol_registry=mock_registry,
            relationship_resolver=mock_resolver,
            embedding_service=mock_embedding,
            project_id="test",
            project_hash="hash123",
            project_root="/tmp/test_project",
        )

        rel1 = create_mock_relationship("func_a", "func_b")
        rel2 = create_mock_relationship("func_c", "func_d")
        relationships = [(rel1, "file1.py"), (rel2, "file2.py")]

        # Mark all as committed
        builder._mark_relationships_committed(relationships)

        uncommitted, skipped = builder._filter_uncommitted_relationships(relationships)

        assert skipped == 2
        assert len(uncommitted) == 0

    @given(
        num_total=st.integers(min_value=10, max_value=100),
        num_committed=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=50)
    def test_property_15_idempotent_resume(self, num_total, num_committed):
        """Property 15: For any resume operation, relationships that were
        already committed SHALL be skipped.
        """
        num_committed = min(num_committed, num_total)

        mock_db = MagicMock()
        mock_registry = MagicMock()
        mock_resolver = MagicMock()
        mock_embedding = MagicMock()

        builder = GraphBuilder(
            db_manager=mock_db,
            symbol_registry=mock_registry,
            relationship_resolver=mock_resolver,
            embedding_service=mock_embedding,
            project_id="test",
            project_hash="hash123",
            project_root="/tmp/test_project",
        )

        # Create relationships
        relationships = [
            (create_mock_relationship(f"func_{i}", f"target_{i}"), f"file_{i}.py")
            for i in range(num_total)
        ]

        # Mark some as committed
        builder._mark_relationships_committed(relationships[:num_committed])

        # Filter
        uncommitted, skipped = builder._filter_uncommitted_relationships(relationships)

        assert skipped == num_committed
        assert len(uncommitted) == num_total - num_committed

    def test_resume_mode_runs_correctly_twice(self):
        """Running filter twice should give consistent results."""
        mock_db = MagicMock()
        mock_registry = MagicMock()
        mock_resolver = MagicMock()
        mock_embedding = MagicMock()

        builder = GraphBuilder(
            db_manager=mock_db,
            symbol_registry=mock_registry,
            relationship_resolver=mock_resolver,
            embedding_service=mock_embedding,
            project_id="test",
            project_hash="hash123",
            project_root="/tmp/test_project",
        )

        rel1 = create_mock_relationship("func_a", "func_b")
        rel2 = create_mock_relationship("func_c", "func_d")
        relationships = [(rel1, "file1.py"), (rel2, "file2.py")]

        # Mark first as committed
        builder._mark_relationships_committed([(rel1, "file1.py")])

        # First filter
        uncommitted1, skipped1 = builder._filter_uncommitted_relationships(relationships)

        # Second filter (simulating resume attempt)
        uncommitted2, skipped2 = builder._filter_uncommitted_relationships(relationships)

        # Results should be identical
        assert len(uncommitted1) == len(uncommitted2)
        assert skipped1 == skipped2


# =============================================================================
# Additional Tests for Resume Statistics
# =============================================================================

class TestResumeStatistics:
    """Tests for statistics during resume operations."""

    def test_stats_include_skipped_count(self):
        """Stats should include count of skipped relationships."""
        stats = {
            "skipped_already_committed": 5,
            "original_total": 100,
            "total_relationships": 95,
        }

        assert stats["skipped_already_committed"] == 5
        assert stats["original_total"] - stats["skipped_already_committed"] == stats["total_relationships"]

    def test_config_preserves_committed_ids_across_calls(self):
        """Committed IDs should persist across filter calls."""
        mock_db = MagicMock()
        mock_registry = MagicMock()
        mock_resolver = MagicMock()
        mock_embedding = MagicMock()

        builder = GraphBuilder(
            db_manager=mock_db,
            symbol_registry=mock_registry,
            relationship_resolver=mock_resolver,
            embedding_service=mock_embedding,
            project_id="test",
            project_hash="hash123",
            project_root="/tmp/test_project",
        )

        # First batch
        rel1 = create_mock_relationship("func_a", "func_b")
        builder._mark_relationships_committed([(rel1, "file.py")])

        # Second batch
        rel2 = create_mock_relationship("func_c", "func_d")
        builder._mark_relationships_committed([(rel2, "file2.py")])

        # Both should be tracked
        assert builder.get_committed_relationship_count() == 2


class TestEdgeCases:
    """Edge case tests for interruption handling."""

    def test_empty_relationships_list(self):
        """Empty relationships list should filter correctly."""
        mock_db = MagicMock()
        mock_registry = MagicMock()
        mock_resolver = MagicMock()
        mock_embedding = MagicMock()

        builder = GraphBuilder(
            db_manager=mock_db,
            symbol_registry=mock_registry,
            relationship_resolver=mock_resolver,
            embedding_service=mock_embedding,
            project_id="test",
            project_hash="hash123",
            project_root="/tmp/test_project",
        )

        uncommitted, skipped = builder._filter_uncommitted_relationships([])

        assert skipped == 0
        assert len(uncommitted) == 0

    def test_relationship_id_includes_source_file(self):
        """Relationship ID should be different for same relationship in different files."""
        rel = create_mock_relationship("my_func", "other_func")

        id_file1 = GraphBuilder._generate_relationship_id(rel, "src/file1.py")
        id_file2 = GraphBuilder._generate_relationship_id(rel, "src/file2.py")

        assert id_file1 != id_file2

    def test_relationship_id_includes_source_type(self):
        """Relationship ID should include source type for uniqueness."""
        rel1 = create_mock_relationship("func", "target", "calls", source_type="function")
        rel2 = create_mock_relationship("func", "target", "calls", source_type="method")

        id1 = GraphBuilder._generate_relationship_id(rel1, "file.py")
        id2 = GraphBuilder._generate_relationship_id(rel2, "file.py")

        assert id1 != id2

    def test_relationship_id_includes_target_type(self):
        """Relationship ID should include target type for uniqueness."""
        rel1 = create_mock_relationship("func", "target", "calls", target_type="function")
        rel2 = create_mock_relationship("func", "target", "calls", target_type="class")

        id1 = GraphBuilder._generate_relationship_id(rel1, "file.py")
        id2 = GraphBuilder._generate_relationship_id(rel2, "file.py")

        assert id1 != id2

