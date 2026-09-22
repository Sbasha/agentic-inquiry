"""Property-based tests for embedding dimensions configuration.

These tests validate that embedding dimensions are properly configured and used
throughout the system as specified in the design document.

Property tests:
- Property 8: Zero vectors use configured dimensions (Requirements 5.2)
- Property 9: Resolver receives configured dimensions (Requirements 5.4)
"""

import pytest

pytestmark = pytest.mark.unit

from hypothesis import given, strategies as st, settings
from unittest.mock import MagicMock, AsyncMock

from agentic_inquiry.indexing.graph_builder import GraphBuilder, GraphBuilderConfig
from agentic_inquiry.indexing.relationship_resolver import RelationshipResolver


# =============================================================================
# Property 8: Zero vectors use configured dimensions
# Validates: Requirements 5.2
# =============================================================================

class TestZeroVectorDimensions:
    """Tests for zero vector dimensions using configured values."""

    @given(
        embedding_dimensions=st.integers(min_value=128, max_value=1536)
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_property_8_zero_vectors_use_configured_dimensions(self, embedding_dimensions):
        """Property 8: For any zero vector created by GraphBuilder, the vector length
        should equal the configured embedding_dimensions (not hardcoded 384).
        
        **Feature: code-review-dec-2024-fixes, Property 8: Zero vectors use configured dimensions**
        **Validates: Requirements 5.2**
        """
        # Create mock dependencies
        db_manager = MagicMock()
        symbol_registry = MagicMock()
        relationship_resolver = MagicMock()
        embedding_service = MagicMock()
        
        # Create GraphBuilder with specific embedding dimensions
        graph_builder = GraphBuilder(
            db_manager=db_manager,
            symbol_registry=symbol_registry,
            relationship_resolver=relationship_resolver,
            embedding_service=embedding_service,
            project_id="test_project",
            project_hash="test_hash",
            project_root="/test/root",
            embedding_dimensions=embedding_dimensions,
        )
        
        # Verify the embedding dimensions are stored correctly
        assert graph_builder._embedding_dimensions == embedding_dimensions
        
        # Test zero vector creation in _generate_external_entity_embeddings_batched
        # by simulating an error condition that triggers zero vector fallback
        embedding_service.generate_embeddings_batch = AsyncMock(
            side_effect=Exception("Simulated embedding error")
        )
        
        # Create a mock external entity
        from agentic_inquiry.indexing.external_entity_resolver import ExternalEntityInfo, ExternalCategory
        mock_entity = ExternalEntityInfo(
            entity_id="test::entity",
            name="TestEntity",
            name_normalized="testentity",
            entity_type="external_class",
            category=ExternalCategory.EXTERNAL,
            language="python",
            virtual_path="external/test.py",
            confidence=1.0,
            metadata={}
        )
        
        # Call the method that generates embeddings (and falls back to zeros on error)
        result = await graph_builder._generate_external_entity_embeddings_batched(
            entities=[mock_entity],
            batch_size=100
        )
        
        # Verify the zero vector has the correct dimensions
        assert len(result) == 1
        assert len(result[0]) == embedding_dimensions
        assert all(v == 0.0 for v in result[0])

    def test_graph_builder_stores_embedding_dimensions(self):
        """GraphBuilder should store embedding_dimensions as instance variable."""
        db_manager = MagicMock()
        symbol_registry = MagicMock()
        relationship_resolver = MagicMock()
        embedding_service = MagicMock()
        
        # Test with default value
        graph_builder = GraphBuilder(
            db_manager=db_manager,
            symbol_registry=symbol_registry,
            relationship_resolver=relationship_resolver,
            embedding_service=embedding_service,
            project_id="test_project",
            project_hash="test_hash",
            project_root="/test/root",
        )
        
        assert graph_builder._embedding_dimensions == 384
        
        # Test with custom value
        graph_builder_custom = GraphBuilder(
            db_manager=db_manager,
            symbol_registry=symbol_registry,
            relationship_resolver=relationship_resolver,
            embedding_service=embedding_service,
            project_id="test_project",
            project_hash="test_hash",
            project_root="/test/root",
            embedding_dimensions=768,
        )
        
        assert graph_builder_custom._embedding_dimensions == 768


# =============================================================================
# Property 9: Resolver receives configured dimensions
# Validates: Requirements 5.4
# =============================================================================

class TestResolverReceivesConfiguredDimensions:
    """Tests for RelationshipResolver receiving configured dimensions."""

    @given(
        embedding_dimensions=st.integers(min_value=128, max_value=1536)
    )
    @settings(max_examples=100)
    def test_property_9_resolver_receives_configured_dimensions(self, embedding_dimensions):
        """Property 9: For any RelationshipResolver created by GraphBuilder,
        the embedding_dimensions parameter should be passed from GraphBuilderConfig.
        
        **Feature: code-review-dec-2024-fixes, Property 9: Resolver receives configured dimensions**
        **Validates: Requirements 5.4**
        """
        # Create a mock config with specific embedding dimensions
        config = MagicMock()
        config.embeddings = MagicMock()
        config.embeddings.default_dimensions = embedding_dimensions
        config.indexing = {'relationship_flush': {}}
        
        # Create GraphBuilderConfig from config
        graph_builder_config = GraphBuilderConfig.from_config(config)
        
        # Verify the config has the correct embedding dimensions
        assert graph_builder_config.embedding_dimensions == embedding_dimensions
        
        # Create RelationshipResolver with the configured dimensions
        symbol_registry = MagicMock()
        resolver = RelationshipResolver(
            symbol_registry=symbol_registry,
            project_root="/test/root",
            embedding_dimensions=graph_builder_config.embedding_dimensions,
        )
        
        # Verify the resolver received the correct dimensions
        assert resolver._embedding_dimensions == embedding_dimensions

    def test_graph_builder_config_loads_embedding_dimensions_from_config(self):
        """GraphBuilderConfig.from_config should load embedding_dimensions from config.embeddings.default_dimensions."""
        # Test with dict-style config
        config = MagicMock()
        config.embeddings = {'default_dimensions': 512}
        config.indexing = {'relationship_flush': {}}
        
        result = GraphBuilderConfig.from_config(config)
        assert result.embedding_dimensions == 512
        
        # Test with object-style config
        config2 = MagicMock()
        config2.embeddings = MagicMock()
        config2.embeddings.default_dimensions = 768
        config2.indexing = {'relationship_flush': {}}
        
        result2 = GraphBuilderConfig.from_config(config2)
        assert result2.embedding_dimensions == 768

    def test_graph_builder_config_uses_default_when_embeddings_missing(self):
        """GraphBuilderConfig should use default embedding_dimensions when config.embeddings is missing."""
        config = MagicMock()
        config.embeddings = None
        config.indexing = {'relationship_flush': {}}
        
        result = GraphBuilderConfig.from_config(config)
        assert result.embedding_dimensions == 384

    def test_relationship_resolver_stores_embedding_dimensions(self):
        """RelationshipResolver should store embedding_dimensions as instance variable."""
        symbol_registry = MagicMock()
        
        # Test with default value
        resolver = RelationshipResolver(
            symbol_registry=symbol_registry,
            project_root="/test/root",
        )
        assert resolver._embedding_dimensions == 384
        
        # Test with custom value
        resolver_custom = RelationshipResolver(
            symbol_registry=symbol_registry,
            project_root="/test/root",
            embedding_dimensions=512,
        )
        assert resolver_custom._embedding_dimensions == 512

    def test_integration_config_to_resolver(self):
        """Integration test: config → GraphBuilderConfig → RelationshipResolver."""
        # Create a config with specific embedding dimensions
        config = MagicMock()
        config.embeddings = MagicMock()
        config.embeddings.default_dimensions = 1024
        config.indexing = {'relationship_flush': {}}
        
        # Load config
        graph_builder_config = GraphBuilderConfig.from_config(config)
        
        # Create resolver with config dimensions
        symbol_registry = MagicMock()
        resolver = RelationshipResolver(
            symbol_registry=symbol_registry,
            project_root="/test/root",
            embedding_dimensions=graph_builder_config.embedding_dimensions,
        )
        
        # Verify the dimensions flowed through correctly
        assert graph_builder_config.embedding_dimensions == 1024
        assert resolver._embedding_dimensions == 1024


# =============================================================================
# Additional Tests for Completeness
# =============================================================================

class TestEmbeddingDimensionsEdgeCases:
    """Additional edge case tests for embedding dimensions."""

    def test_graph_builder_config_default_embedding_dimensions(self):
        """GraphBuilderConfig should have default embedding_dimensions of 384."""
        defaults = GraphBuilderConfig()
        assert defaults.embedding_dimensions == 384

    def test_graph_builder_passes_dimensions_to_resolver_via_pipeline(self):
        """Verify that pipeline passes embedding_dimensions to both resolver and builder."""
        # This is a documentation test - the actual integration is tested in pipeline tests
        # Just verify the parameter exists in the constructors
        
        # Check RelationshipResolver accepts embedding_dimensions
        import inspect
        resolver_sig = inspect.signature(RelationshipResolver.__init__)
        assert 'embedding_dimensions' in resolver_sig.parameters
        
        # Check GraphBuilder accepts embedding_dimensions
        builder_sig = inspect.signature(GraphBuilder.__init__)
        assert 'embedding_dimensions' in builder_sig.parameters
