import unittest

import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.embeddings.hashing import HashingEmbedder
from agentic_inquiry.embeddings.registry import EmbeddingRegistry
from agentic_inquiry.embeddings.sentence_transformer import SentenceTransformerEmbedder


class TestEmbeddingRegistry(unittest.TestCase):
    def test_default_must_be_explicit(self):
        from agentic_inquiry.exceptions import StorageError
        
        registry = EmbeddingRegistry()

        with self.assertRaises(StorageError):
            registry.get("any", "column")

        custom = HashingEmbedder(ndims=32)
        registry.configure_default_embedder(custom)
        embedder, dims = registry.get_configuration("fallback", "vector")
        self.assertIs(embedder, custom)
        self.assertEqual(dims, 32)

    def test_register_records_expected_dimensions(self):
        registry = EmbeddingRegistry()
        embedder = SentenceTransformerEmbedder(ndims=48)
        registry.register("table", "column", embedder)

        configured, dims = registry.get_configuration("table", "column")
        self.assertIs(configured, embedder)
        self.assertEqual(dims, 48)

    def test_register_with_custom_expected_dimensions(self):
        registry = EmbeddingRegistry()
        embedder = HashingEmbedder(ndims=128)
        registry.register("table", "column", embedder, ndims=64)

        self.assertEqual(registry.get_expected_dimensions("table", "column"), 64)

    def test_configure_default_embedder_once(self):
        """Test that configuring embedder twice logs warning but succeeds (idempotent)."""
        import logging

        registry = EmbeddingRegistry()
        registry.configure_default_embedder(HashingEmbedder())

        # Second configuration should succeed with warning (idempotent behavior)
        # This is expected in test environments
        with self.assertLogs('agentic_inquiry.embeddings.registry', level=logging.WARNING) as cm:
            registry.configure_default_embedder(HashingEmbedder())

        # Verify warning was logged
        self.assertTrue(any('already been configured' in msg for msg in cm.output))


class TestHybridEmbeddings(unittest.TestCase):
    """Tests for the hybrid embedding strategy (see docs/design/hybrid-embedding-strategy.md)."""

    def test_configure_hybrid_embeddings_registers_hashing_for_relationships(self):
        """Test that configure_hybrid_embeddings registers HashingEmbedder for graph_relationships."""
        registry = EmbeddingRegistry()
        registry.configure_default_embedder(SentenceTransformerEmbedder(ndims=384))
        registry.configure_hybrid_embeddings()

        # Verify graph_relationships uses HashingEmbedder
        embedder, dims = registry.get_configuration("graph_relationships", "vector")
        self.assertIsInstance(embedder, HashingEmbedder)
        self.assertEqual(dims, 384)  # Should match default embedder's dims

    def test_configure_hybrid_embeddings_uses_default_ndims(self):
        """Test that hybrid embeddings use the default embedder's dimensions."""
        registry = EmbeddingRegistry()
        registry.configure_default_embedder(HashingEmbedder(ndims=256))
        registry.configure_hybrid_embeddings()

        # Should use the default embedder's 256 dims
        embedder, dims = registry.get_configuration("graph_relationships", "vector")
        self.assertEqual(dims, 256)

    def test_configure_hybrid_embeddings_with_explicit_ndims(self):
        """Test that explicit ndims overrides the default."""
        registry = EmbeddingRegistry()
        registry.configure_default_embedder(HashingEmbedder(ndims=384))
        registry.configure_hybrid_embeddings(ndims=128)

        # Should use explicitly provided 128 dims
        embedder, dims = registry.get_configuration("graph_relationships", "vector")
        self.assertEqual(dims, 128)

    def test_configure_hybrid_embeddings_without_default_raises_error(self):
        """Test that configure_hybrid_embeddings raises error without default or explicit dims."""
        from agentic_inquiry.exceptions import StorageError

        registry = EmbeddingRegistry()
        # No default embedder configured and no explicit ndims

        with self.assertRaises(StorageError) as ctx:
            registry.configure_hybrid_embeddings()

        self.assertIn("No dimensions provided", str(ctx.exception))
        self.assertIn("configure_default_embedder", str(ctx.exception))

    def test_configure_hybrid_embeddings_with_explicit_dims_no_default(self):
        """Test that explicit ndims works even without a default embedder."""
        registry = EmbeddingRegistry()
        # No default embedder, but explicit dims provided
        registry.configure_hybrid_embeddings(ndims=384)

        embedder, dims = registry.get_configuration("graph_relationships", "vector")
        self.assertIsInstance(embedder, HashingEmbedder)
        self.assertEqual(dims, 384)

    def test_other_tables_still_use_default_embedder(self):
        """Test that non-relationship tables still use the default ML embedder."""
        registry = EmbeddingRegistry()
        default_embedder = SentenceTransformerEmbedder(ndims=384)
        registry.configure_default_embedder(default_embedder)
        registry.configure_hybrid_embeddings()

        # graph_relationships should use HashingEmbedder
        rel_embedder, _ = registry.get_configuration("graph_relationships", "vector")
        self.assertIsInstance(rel_embedder, HashingEmbedder)

        # Other tables should still use the default SentenceTransformer
        chunk_embedder, _ = registry.get_configuration("document_chunks", "vector")
        self.assertIs(chunk_embedder, default_embedder)

        entity_embedder, _ = registry.get_configuration("graph_entities", "vector")
        self.assertIs(entity_embedder, default_embedder)


if __name__ == "__main__":
    unittest.main()
