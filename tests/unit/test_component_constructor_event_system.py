"""Tests for component constructor changes to accept EventSystem parameter.

This test module verifies that SearchService, ParserChain, FileWatcher, and
IndexingPipeline all properly accept and use EventSystem instances passed to
their constructors.

Requirements tested: 4.2, 4.3, 4.4, 4.5
"""

import pytest

pytestmark = pytest.mark.unit
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from agent_vault.config import Config
from agent_vault.events.system import EventSystem
from agent_vault.search.service import SearchService
from agent_vault.parsers.chain import ParserChain
from agent_vault.watching.watcher import FileWatcher
from agent_vault.indexing.pipeline import IndexingPipeline


@pytest_asyncio.fixture
async def mock_event_system():
    """Create a mock EventSystem for testing."""
    event_system = AsyncMock(spec=EventSystem)
    event_system.emit = AsyncMock()
    event_system.subscribe = MagicMock()
    return event_system


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager."""
    db_manager = MagicMock()
    db_manager.get_table = MagicMock()
    return db_manager


@pytest.fixture
def mock_storage_facade():
    """Create a mock StorageFacade for SearchService."""
    storage = MagicMock()
    storage.project_id = "test_project"
    storage.vector_provider = MagicMock()
    storage.graph_provider = MagicMock()
    storage.vector_search = AsyncMock(return_value=[])
    storage.fts_search = AsyncMock(return_value=[])
    storage.get_entity = AsyncMock(return_value=None)
    storage.get_relationships = AsyncMock(return_value=[])
    storage.query_raw = AsyncMock(return_value=[{
        "id": "ent_1",
        "name": "Module.Class",
        "type": "class",
        "doc_id": "doc_1",
        "file_path": "path/to/file.py",
        "project_id": "test_project",
    }])
    storage.vector_search_raw = AsyncMock(return_value=[])
    return storage


@pytest.fixture
def test_config(tmp_path: Path):
    """Create a test configuration."""
    config = Config.load()
    config.storage.root = str(tmp_path)
    config.storage.default_project_id = "test_project"
    return config


class TestSearchServiceConstructor:
    """Test SearchService constructor accepts event_system parameter."""

    @pytest.mark.asyncio
    async def test_search_service_accepts_event_system(
        self, mock_storage_facade, test_config, mock_event_system
    ):
        """Test SearchService with event_system parameter.

        Validates: Requirement 4.3
        """
        # Create SearchService with storage (StorageFacade) and event_system
        service = SearchService(
            storage=mock_storage_facade,
            config=test_config,
            event_system=mock_event_system,
            project_id="test_project",
        )

        # Verify event_system is stored
        assert service.event_system is mock_event_system

        # Verify other attributes are initialized
        assert service.storage_facade is mock_storage_facade
        assert service.config is test_config
        assert service.project_id == "test_project"

    @pytest.mark.asyncio
    async def test_search_service_uses_provided_event_system(
        self, mock_storage_facade, test_config, mock_event_system
    ):
        """Test SearchService uses the provided event_system for sub-services.

        Validates: Requirement 4.3
        """
        service = SearchService(
            storage=mock_storage_facade,
            config=test_config,
            event_system=mock_event_system,
            project_id="test_project",
        )

        await service.resolve_entity(
            entity_name="Module.Class",
            project_id="test_project",
        )

        emitted = [call.args[0] for call in mock_event_system.emit.call_args_list]
        assert "search.resolve_entity.started" in emitted
        assert "search.resolve_entity.completed" in emitted


class TestParserChainConstructor:
    """Test ParserChain constructor accepts event_system parameter."""

    @pytest.mark.asyncio
    async def test_parser_chain_accepts_event_system(
        self, test_config, mock_event_system
    ):
        """Test ParserChain with event_system parameter.
        
        Validates: Requirement 4.4
        """
        # Create ParserChain with event_system
        chain = ParserChain(
            event_system=mock_event_system,
            config=test_config,
        )
        
        # Verify event_system is stored
        assert chain.event_system is mock_event_system
        
        # Verify other attributes are initialized
        assert chain.config is test_config
        assert chain.parser_names == [
            "unified_code",
            "salesforce_metadata",
            "document",
            "fallback_text",
        ]

    @pytest.mark.asyncio
    async def test_parser_chain_with_custom_parser_names(
        self, test_config, mock_event_system
    ):
        """Test ParserChain with custom parser names and event_system.
        
        Validates: Requirement 4.4
        """
        custom_parsers = ["unified_code", "document"]
        
        chain = ParserChain(
            event_system=mock_event_system,
            parser_names=custom_parsers,
            config=test_config,
        )
        
        assert chain.event_system is mock_event_system
        assert chain.parser_names == custom_parsers


class TestFileWatcherConstructor:
    """Test FileWatcher constructor accepts event_system parameter."""

    @pytest.mark.asyncio
    async def test_file_watcher_accepts_event_system(
        self, test_config, mock_event_system
    ):
        """Test FileWatcher with event_system parameter.
        
        Validates: Requirement 4.5
        """
        # Create FileWatcher with event_system
        watcher = FileWatcher(
            event_system=mock_event_system,
            config=test_config,
            project_id="test_project",
        )
        
        # Verify event_system is stored
        assert watcher.event_system is mock_event_system
        
        # Verify other attributes are initialized
        assert watcher.file_tracker is not None
        assert watcher.debounce_seconds == 0.5

    @pytest.mark.asyncio
    async def test_file_watcher_with_custom_debounce(
        self, test_config, mock_event_system
    ):
        """Test FileWatcher with custom debounce and event_system.
        
        Validates: Requirement 4.5
        """
        watcher = FileWatcher(
            event_system=mock_event_system,
            debounce_seconds=1.0,
            config=test_config,
            project_id="test_project",
        )
        
        assert watcher.event_system is mock_event_system
        assert watcher.debounce_seconds == 1.0


class TestIndexingPipelineConstructor:
    """Test IndexingPipeline constructor requires event_system parameter."""

    @pytest.mark.asyncio
    async def test_indexing_pipeline_requires_event_system(
        self, mock_db_manager, test_config, mock_event_system
    ):
        """Test IndexingPipeline requires event_system parameter.
        
        Validates: Requirement 4.2
        """
        # Create IndexingPipeline with event_system
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=test_config,
            project_id="test_project",
            event_system=mock_event_system,
        )
        
        # Verify event_system is stored
        assert pipeline.event_system is mock_event_system
        
        # Verify other attributes are initialized
        assert pipeline.db_manager is mock_db_manager
        assert pipeline.config is test_config
        assert pipeline.project_id == "test_project"

    @pytest.mark.asyncio
    async def test_indexing_pipeline_event_system_optional(
        self, mock_db_manager, test_config
    ):
        """Test IndexingPipeline works without event_system parameter.

        Since event_system is now optional, IndexingPipeline should be
        creatable without it. Events just won't be emitted.
        """
        # Create IndexingPipeline without event_system should succeed
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=test_config,
            project_id="test_project",
        )

        # Verify pipeline was created (event_system should be None)
        assert pipeline.event_system is None
        assert pipeline.project_id == "test_project"
