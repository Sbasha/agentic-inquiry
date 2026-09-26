"""Custom assertion helpers for tests.

Provides reusable assertion functions for common test patterns.
"""


def assert_chunks_equal(chunk1, chunk2, ignore_fields=None):
    """Assert two chunks are equal, optionally ignoring specific fields.

    Args:
        chunk1: First chunk to compare
        chunk2: Second chunk to compare
        ignore_fields: List of field names to ignore in comparison
    """
    ignore_fields = ignore_fields or []

    for field in ["content", "doc_id", "chunk_id", "metadata"]:
        if field not in ignore_fields:
            assert getattr(chunk1, field) == getattr(chunk2, field), (
                f"Field {field} differs: {getattr(chunk1, field)} != {getattr(chunk2, field)}"
            )


def assert_valid_embedding(embedding, expected_dim=384):
    """Assert an embedding is valid.

    Args:
        embedding: Embedding vector to validate
        expected_dim: Expected dimensionality
    """
    assert embedding is not None, "Embedding is None"
    assert len(embedding) == expected_dim, (
        f"Embedding dimension {len(embedding)} != expected {expected_dim}"
    )
    assert all(isinstance(x, (int, float)) for x in embedding), (
        "Embedding contains non-numeric values"
    )
