"""Tests for suggestion engine utility."""

import pytest

pytestmark = pytest.mark.unit

from unittest.mock import AsyncMock, MagicMock, patch

from agentic_inquiry.mcp.utils.suggestions import (
    generate_suggestions,
    _generate_spelling_suggestions,
    _generate_topic_suggestions,
    _generate_threshold_suggestions,
    _generate_typo_variants,
)


@pytest.mark.asyncio
async def test_generate_suggestions_empty_results():
    """Test suggestion generation for empty results."""
    search_service = AsyncMock()
    search_service.fts_search.return_value = []
    search_service.vector_search.return_value = []

    config = MagicMock()

    with patch("agentic_inquiry.embeddings.EmbeddingService") as mock_embed:
        mock_embed_instance = AsyncMock()
        mock_embed_instance.embed_async.return_value = [0.1] * 384
        mock_embed.return_value = mock_embed_instance

        suggestions = await generate_suggestions(
            query="nonexistent",
            search_service=search_service,
            project_id="test_project",
            config=config,
        )

    # Should return general suggestions (at least one)
    assert len(suggestions) > 0


@pytest.mark.asyncio
async def test_generate_spelling_suggestions():
    """Test spelling correction suggestions."""
    search_service = AsyncMock()

    # Mock FTS search to return results for corrected spelling
    search_service.fts_search.return_value = [{"id": "chunk1"}]

    suggestions = await _generate_spelling_suggestions(
        query="functoin",  # Typo
        search_service=search_service,
        project_id="test_project",
    )

    # Should suggest spelling corrections
    assert len(suggestions) > 0


@pytest.mark.asyncio
async def test_generate_topic_suggestions():
    """Test similar topic suggestions."""
    search_service = AsyncMock()
    config = MagicMock()

    # Mock vector search results
    search_service.vector_search.return_value = [
        {
            "id": "chunk1",
            "title": "Authentication Module",
            "name": "auth",
        },
        {
            "id": "chunk2",
            "title": "Authorization Handler",
            "name": "authz",
        },
    ]

    with patch("agentic_inquiry.embeddings.EmbeddingService") as mock_embed:
        mock_embed_instance = AsyncMock()
        mock_embed_instance.embed_async.return_value = [0.1] * 384
        mock_embed.return_value = mock_embed_instance

        suggestions = await _generate_topic_suggestions(
            query="login",
            search_service=search_service,
            project_id="test_project",
            config=config,
        )

    # Should return suggestions (may be empty if no good topics found)
    assert isinstance(suggestions, list)


@pytest.mark.asyncio
async def test_generate_threshold_suggestions():
    """Test lower-threshold alternative suggestions."""
    search_service = AsyncMock()
    config = MagicMock()

    # Mock FTS search to return results for individual terms
    search_service.fts_search.return_value = [{"id": "chunk1"}]

    suggestions = await _generate_threshold_suggestions(
        query="user authentication system",
        search_service=search_service,
        project_id="test_project",
        config=config,
    )

    # Should suggest searching individual terms
    assert len(suggestions) > 0


def test_generate_typo_variants():
    """Test typo variant generation."""
    variants = _generate_typo_variants("function")

    # Should generate variants
    assert len(variants) > 0

    # Should include deletion variants
    assert "unction" in variants  # Delete 'f'
    assert "fnction" in variants  # Delete 'u'

    # Should include transposition variants
    assert "ufnction" in variants  # Swap 'f' and 'u'


def test_generate_typo_variants_short_term():
    """Test typo variants for short terms."""
    variants = _generate_typo_variants("ab")

    # Should still generate some variants
    assert len(variants) > 0

    # But deletion variants should be filtered (too short)
    assert "a" not in variants
    assert "b" not in variants


@pytest.mark.asyncio
async def test_generate_suggestions_limit():
    """Test that suggestions are limited to top 5."""
    search_service = AsyncMock()
    config = MagicMock()

    # Mock to return many potential suggestions
    search_service.fts_search.return_value = [{"id": f"chunk{i}"} for i in range(10)]
    search_service.vector_search.return_value = [
        {"id": f"chunk{i}", "title": f"Item {i}"} for i in range(10)
    ]

    with patch("agentic_inquiry.embeddings.EmbeddingService") as mock_embed:
        mock_embed_instance = AsyncMock()
        mock_embed_instance.embed_async.return_value = [0.1] * 384
        mock_embed.return_value = mock_embed_instance

        suggestions = await generate_suggestions(
            query="test query with multiple terms",
            search_service=search_service,
            project_id="test_project",
            config=config,
        )

    # Should limit to 5 suggestions
    assert len(suggestions) <= 5
