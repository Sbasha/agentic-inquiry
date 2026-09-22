"""Tests for sentence-transformers library assumptions.

These tests verify that sentence-transformers behaves as expected
and that our assumptions about embedding generation are correct.

Run with: pytest tests/adapters/test_sentence_transformers.py -v
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.adapters, pytest.mark.model, pytest.mark.slow]


class TestEmbeddingDimensions:
    """Test embedding dimension assumptions."""

    def test_all_minilm_produces_384_dimensions(self, skip_if_no_sentence_transformers):
        """all-MiniLM-L6-v2 produces 384-dimensional embeddings."""
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        embedding = model.encode("test text")

        assert embedding.shape == (384,)

    def test_embedding_is_normalized(self, skip_if_no_sentence_transformers):
        """Embeddings are normalized (unit length)."""
        import numpy as np
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        embedding = model.encode("test text", normalize_embeddings=True)

        # L2 norm should be approximately 1
        norm = np.linalg.norm(embedding)
        assert abs(norm - 1.0) < 0.001


class TestBatchProcessing:
    """Test batch processing behavior."""

    def test_batch_encoding_same_as_individual(self, skip_if_no_sentence_transformers):
        """Batch encoding produces same results as individual."""
        import numpy as np
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")

        texts = ["first text", "second text", "third text"]

        # Individual encoding
        individual = [model.encode(t) for t in texts]

        # Batch encoding
        batch = model.encode(texts)

        for i, text in enumerate(texts):
            np.testing.assert_array_almost_equal(
                individual[i], batch[i], decimal=5,
                err_msg=f"Mismatch for text: {text}"
            )

    def test_empty_text_handling(self, skip_if_no_sentence_transformers):
        """Empty text produces valid embedding (not NaN)."""
        import numpy as np
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        embedding = model.encode("")

        assert not np.isnan(embedding).any()
        assert embedding.shape == (384,)


class TestSimilarityCalculation:
    """Test similarity calculation assumptions."""

    def test_identical_texts_have_similarity_one(self, skip_if_no_sentence_transformers):
        """Identical texts have cosine similarity of 1."""
        from sentence_transformers import SentenceTransformer, util

        model = SentenceTransformer("all-MiniLM-L6-v2")

        text = "The quick brown fox jumps over the lazy dog"
        emb1 = model.encode(text)
        emb2 = model.encode(text)

        similarity = util.cos_sim(emb1, emb2).item()
        assert abs(similarity - 1.0) < 0.001

    def test_similar_texts_have_high_similarity(self, skip_if_no_sentence_transformers):
        """Semantically similar texts have high similarity."""
        from sentence_transformers import SentenceTransformer, util

        model = SentenceTransformer("all-MiniLM-L6-v2")

        emb1 = model.encode("The cat sat on the mat")
        emb2 = model.encode("A feline rested on a rug")

        similarity = util.cos_sim(emb1, emb2).item()
        assert similarity > 0.5, f"Expected high similarity, got {similarity}"

    def test_dissimilar_texts_have_low_similarity(self, skip_if_no_sentence_transformers):
        """Semantically different texts have low similarity."""
        from sentence_transformers import SentenceTransformer, util

        model = SentenceTransformer("all-MiniLM-L6-v2")

        emb1 = model.encode("Machine learning algorithms process data")
        emb2 = model.encode("The weather is sunny today")

        similarity = util.cos_sim(emb1, emb2).item()
        assert similarity < 0.5, f"Expected low similarity, got {similarity}"


class TestTokenization:
    """Test tokenization behavior."""

    def test_long_text_truncation(self, skip_if_no_sentence_transformers):
        """Long texts are truncated without error."""
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")

        # Create text longer than max tokens (512 for most models)
        long_text = "word " * 1000  # ~1000 words

        # Should not raise
        embedding = model.encode(long_text)
        assert embedding.shape == (384,)

    def test_special_characters_handled(self, skip_if_no_sentence_transformers):
        """Special characters don't cause encoding errors."""
        import numpy as np
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")

        special_texts = [
            "def func(): pass",  # Code
            "SELECT * FROM table",  # SQL
            "path/to/file.py",  # Path
            "@decorator\nclass Foo:\n    pass",  # Python with decorator
            "emoji 😀 test",  # Emoji
            "unicode: αβγδ",  # Greek letters
        ]

        for text in special_texts:
            embedding = model.encode(text)
            assert not np.isnan(embedding).any(), f"NaN for: {text}"
            assert embedding.shape == (384,), f"Wrong shape for: {text}"
