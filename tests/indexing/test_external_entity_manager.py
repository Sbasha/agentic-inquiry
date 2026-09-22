"""Unit tests for ExternalEntityManager."""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock
import numpy as np

from agent_vault.indexing.external_entity_manager import ExternalEntityManager


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager."""
    db = AsyncMock()
    db.add_graph_entities = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mock_embedding_service():
    """Create a mock embedding service."""
    service = MagicMock()
    service.embed_batch_async = AsyncMock(
        return_value=[np.random.rand(384).astype(np.float32) for _ in range(10)]
    )
    service.get_embedder_configuration = MagicMock(
        return_value=(MagicMock(generate=lambda x: [np.random.rand(384).astype(np.float32)]), 384)
    )
    return service


@pytest.fixture
def mock_external_resolver():
    """Create a mock external resolver."""
    from agent_vault.indexing.external_entity_resolver import ExternalCategory

    resolver = MagicMock()

    def mock_resolve(target_name, target_type, language="", source_file="", metadata=None):
        info = MagicMock()
        info.entity_id = f"ext_{target_name}_{language}"
        info.name = target_name
        info.entity_type = target_type
        info.language = language
        info.virtual_path = f"external/{language}/{target_name}"
        info.category = ExternalCategory.EXTERNAL
        return info

    resolver.resolve = mock_resolve
    return resolver


@pytest.fixture
def external_entity_manager(mock_db_manager, mock_embedding_service, mock_external_resolver):
    """Create an ExternalEntityManager instance."""
    return ExternalEntityManager(
        project_id="test_project",
        project_hash="abc123",
        db_manager=mock_db_manager,
        embedding_service=mock_embedding_service,
        external_resolver=mock_external_resolver,
        embedding_dimensions=384,
    )


class TestExternalEntityManager:
    """Tests for ExternalEntityManager."""

    def test_init(self, external_entity_manager):
        """Test initialization."""
        assert external_entity_manager.project_id == "test_project"
        assert external_entity_manager.project_hash == "abc123"
        assert external_entity_manager.pending_count == 0

    def test_queue_external_entity(self, external_entity_manager):
        """Test queuing an external entity."""
        info = external_entity_manager.queue_external_entity(
            target_name="pandas",
            target_type="module",
            language="python",
            source_file="test.py",
        )

        assert info is not None
        assert info.name == "pandas"
        assert external_entity_manager.pending_count == 1

    def test_queue_external_entity_deduplication(self, external_entity_manager):
        """Test that duplicate entities are deduplicated."""
        # Queue the same entity twice
        external_entity_manager.queue_external_entity(
            target_name="pandas",
            target_type="module",
            language="python",
        )
        external_entity_manager.queue_external_entity(
            target_name="pandas",
            target_type="module",
            language="python",
        )

        # Should only have one pending entity
        assert external_entity_manager.pending_count == 1

    def test_queue_different_entities(self, external_entity_manager):
        """Test queuing different entities."""
        external_entity_manager.queue_external_entity(
            target_name="pandas",
            target_type="module",
            language="python",
        )
        external_entity_manager.queue_external_entity(
            target_name="numpy",
            target_type="module",
            language="python",
        )

        assert external_entity_manager.pending_count == 2

    def test_clear_pending(self, external_entity_manager):
        """Test clearing pending entities."""
        external_entity_manager.queue_external_entity(
            target_name="pandas",
            target_type="module",
            language="python",
        )
        assert external_entity_manager.pending_count == 1

        external_entity_manager.clear_pending()
        assert external_entity_manager.pending_count == 0

    def test_get_pending_entities(self, external_entity_manager):
        """Test getting pending entities."""
        external_entity_manager.queue_external_entity(
            target_name="pandas",
            target_type="module",
            language="python",
        )

        pending = external_entity_manager.get_pending_entities()
        assert len(pending) == 1
        assert "ext_pandas_python" in pending

    @pytest.mark.asyncio
    async def test_flush_if_needed_below_threshold(self, external_entity_manager):
        """Test that flush doesn't happen below threshold."""
        external_entity_manager.queue_external_entity(
            target_name="pandas",
            target_type="module",
            language="python",
        )

        # Threshold is 10000 by default, we have 1 entity
        result = await external_entity_manager.flush_if_needed(threshold=10000)
        assert result == 0
        assert external_entity_manager.pending_count == 1  # Not cleared

    @pytest.mark.asyncio
    async def test_flush_if_needed_above_threshold(self, external_entity_manager, mock_db_manager):
        """Test that flush happens above threshold."""
        # Queue 5 entities
        for i in range(5):
            external_entity_manager.queue_external_entity(
                target_name=f"module_{i}",
                target_type="module",
                language="python",
            )

        assert external_entity_manager.pending_count == 5

        # Set low threshold
        result = await external_entity_manager.flush_if_needed(threshold=3)

        assert result == 5
        assert external_entity_manager.pending_count == 0  # Cleared
        mock_db_manager.add_graph_entities.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_if_needed_with_event_system(self, external_entity_manager):
        """Test flush emits events when event_system provided."""
        for i in range(3):
            external_entity_manager.queue_external_entity(
                target_name=f"module_{i}",
                target_type="module",
                language="python",
            )

        mock_event_system = AsyncMock()
        mock_event_system.emit = AsyncMock()

        await external_entity_manager.flush_if_needed(
            threshold=2,
            event_system=mock_event_system,
        )

        mock_event_system.emit.assert_called_once()
        call_args = mock_event_system.emit.call_args
        assert call_args[0][0] == "external_entities.flushed"


class TestDetectLanguage:
    """Tests for language detection."""

    def test_detect_language_from_metadata_language(self):
        """Test detecting language from metadata 'language' key."""
        result = ExternalEntityManager.detect_language(
            "test.txt",
            metadata={"language": "Python"}
        )
        assert result == "python"

    def test_detect_language_from_metadata_lang(self):
        """Test detecting language from metadata 'lang' key."""
        result = ExternalEntityManager.detect_language(
            "test.txt",
            metadata={"lang": "JavaScript"}
        )
        assert result == "javascript"

    def test_detect_language_from_extension_python(self):
        """Test detecting Python from extension."""
        assert ExternalEntityManager.detect_language("test.py") == "python"
        assert ExternalEntityManager.detect_language("test.pyi") == "python"

    def test_detect_language_from_extension_javascript(self):
        """Test detecting JavaScript from extension."""
        assert ExternalEntityManager.detect_language("test.js") == "javascript"
        assert ExternalEntityManager.detect_language("test.jsx") == "javascript"

    def test_detect_language_from_extension_typescript(self):
        """Test detecting TypeScript from extension."""
        assert ExternalEntityManager.detect_language("test.ts") == "typescript"
        assert ExternalEntityManager.detect_language("test.tsx") == "typescript"

    def test_detect_language_from_extension_go(self):
        """Test detecting Go from extension."""
        assert ExternalEntityManager.detect_language("test.go") == "go"

    def test_detect_language_from_extension_rust(self):
        """Test detecting Rust from extension."""
        assert ExternalEntityManager.detect_language("test.rs") == "rust"

    def test_detect_language_unknown_extension(self):
        """Test unknown extension returns empty string."""
        assert ExternalEntityManager.detect_language("test.xyz") == ""

    def test_detect_language_no_extension(self):
        """Test file without extension returns empty string."""
        assert ExternalEntityManager.detect_language("Makefile") == ""

    def test_detect_language_metadata_takes_precedence(self):
        """Test that metadata takes precedence over extension."""
        result = ExternalEntityManager.detect_language(
            "test.py",
            metadata={"language": "TypeScript"}
        )
        assert result == "typescript"


class TestCountEntitiesByCategory:
    """Tests for category counting."""

    def test_count_entities_empty_list(self, external_entity_manager):
        """Test counting empty list."""
        result = external_entity_manager._count_entities_by_category([])
        assert result == {}

    def test_count_entities_single_category(self, external_entity_manager):
        """Test counting single category."""
        from agent_vault.indexing.external_entity_resolver import ExternalCategory

        mock_entity = MagicMock()
        mock_entity.category = ExternalCategory.EXTERNAL

        result = external_entity_manager._count_entities_by_category([mock_entity])
        assert result == {"external": 1}

    def test_count_entities_multiple_categories(self, external_entity_manager):
        """Test counting multiple categories."""
        from agent_vault.indexing.external_entity_resolver import ExternalCategory

        entities = []
        for _ in range(3):
            e = MagicMock()
            e.category = ExternalCategory.BUILTIN
            entities.append(e)
        for _ in range(2):
            e = MagicMock()
            e.category = ExternalCategory.EXTERNAL
            entities.append(e)

        result = external_entity_manager._count_entities_by_category(entities)
        assert result == {"builtin": 3, "external": 2}
