"""Integration test for relationship count visibility after indexing.

This test verifies that after an indexing.completed event is emitted,
the relationship count returned by get_project_info matches the actual
count in the database.

Requirements: FR-1.1, AC-1.1
"""

import asyncio
import pytest
from pathlib import Path

pytestmark = pytest.mark.integration

from agent_vault.config import Config, StorageConfig, EventsConfig, EventStoreConfig
from agent_vault.database.lancedb_manager import LanceDBManager
from agent_vault.embeddings.base import Embedder
from agent_vault.embeddings.registry import EmbeddingRegistry
from agent_vault.events.system import EventSystem
from agent_vault.events.types import EventTypes
from agent_vault.indexing.pipeline import IndexingPipeline
from agent_vault.mcp.services.session_manager import SessionManager
from agent_vault.mcp.tools.info import get_project_info
from agent_vault.storage.facade import StorageFacade
from tests.helpers.async_utils import AsyncTestHelper


class _DummyEmbedder(Embedder):
    """Dummy embedder for testing."""

    def __init__(self):
        self._ndims = 384

    def generate(self, texts):
        """Generate dummy embeddings."""
        return [[0.1] * 384 for _ in texts]

    def ndims(self):
        """Return embedding dimensions."""
        return self._ndims


@pytest.fixture
def sample_python_code_with_relationships(tmp_path: Path) -> Path:
    """Create sample Python files that will generate relationships.

    This creates a multi-file project where:
    - module_a.py defines a class and functions
    - module_b.py imports from module_a and uses its classes
    - This creates import relationships and usage relationships
    """
    # Create module_a.py with class and functions
    module_a = tmp_path / "module_a.py"
    module_a_content = '''"""Module A with utilities."""

def helper_function(x: int) -> int:
    """A helper function."""
    return x * 2

class DataProcessor:
    """Process data."""

    def __init__(self):
        self.value = 0

    def process(self, data: int) -> int:
        """Process data."""
        return helper_function(data)
'''
    module_a.write_text(module_a_content)

    # Create module_b.py that imports from module_a
    module_b = tmp_path / "module_b.py"
    module_b_content = '''"""Module B that uses module A."""

from module_a import DataProcessor, helper_function

class Application:
    """Main application."""

    def __init__(self):
        self.processor = DataProcessor()

    def run(self, value: int) -> int:
        """Run the application."""
        result = self.processor.process(value)
        return helper_function(result)
'''
    module_b.write_text(module_b_content)

    return tmp_path


@pytest.mark.asyncio
async def test_relationship_count_after_indexing_completed(
    tmp_path: Path,
    sample_python_code_with_relationships: Path
):
    """Test that relationship count is accurate after indexing.completed event.

    This test verifies AC-1.1: After indexing.completed event, get_project_info
    returns a relationship count that matches the actual count in the database.

    Steps:
    1. Set up project with real code files that create relationships
    2. Index the files using IndexingPipeline
    3. Wait for indexing.completed event
    4. Call get_project_info
    5. Query actual relationship count from database
    6. Verify counts match

    Requirements: FR-1.1, AC-1.1
    """
    # Create config with temp storage and events enabled
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path / "storage"),
        default_project_id="test_project",
        backend="lancedb",
        event_store=EventStoreConfig(path="test_events.db")
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=100,
        batch_size=10,
        flush_interval_seconds=0.1,
    )

    # Initialize services
    db_manager = LanceDBManager.from_config(config)
    storage = await StorageFacade.from_config(config, project_id="test_project")

    # Create event system
    event_system = await EventSystem.from_config(config, project_id="test_project")

    try:
        # Create embedding registry with dummy embedder
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())

        # Create indexing pipeline
        indexing_pipeline = IndexingPipeline(
            db_manager=db_manager,
            config=config,
            project_id="test_project",
            event_system=event_system,
            registry=registry,
            project_root=str(sample_python_code_with_relationships)
        )

        # Create session manager for get_project_info
        session_manager = SessionManager(
            db_manager=storage,
            config=config,
            event_system=event_system
        )

        # Create memory system (required by get_project_info)
        from agent_vault.memory.system import MemorySystem
        from agent_vault.embeddings.service import EmbeddingService

        embedding_service = EmbeddingService(config)
        memory_system = MemorySystem(config, embedding_service, event_system=event_system)
        await memory_system.initialize()

        # Create session
        session = await session_manager.create_session(
            project_id="test_project",
            description="Test session for relationship count validation"
        )
        session_id = session["session_id"]

        # Services dict for get_project_info
        services = {
            "session_manager": session_manager,
            "storage": storage,
            "memory_system": memory_system
        }

        # Index the directory - this should create relationships
        # Store operation_id to track events
        operation_id = None

        async def capture_operation_id(*args, **kwargs):
            """Capture operation_id from event emission."""
            nonlocal operation_id
            if kwargs.get("event_type") == EventTypes.Indexing.STARTED:
                operation_id = kwargs.get("operation_id")

        # Wrap emit to capture operation_id
        original_emit = event_system.emit
        async def wrapped_emit(event_type, **kwargs):
            await capture_operation_id(event_type=event_type, **kwargs)
            return await original_emit(event_type, **kwargs)

        event_system.emit = wrapped_emit

        # Index the directory (wait=True for synchronous completion)
        await indexing_pipeline.index_directory(
            path=str(sample_python_code_with_relationships),
            wait=True
        )

        # Wait for indexing.completed event to be persisted
        assert operation_id is not None, "operation_id should have been captured"

        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: event_system.store.get_operation_events(operation_id),
            lambda events: any(e.event_type == EventTypes.Indexing.COMPLETED for e in events),
            timeout=10.0
        )
        assert success, "indexing.completed event was not persisted in time"

        # Now call get_project_info to get the relationship count
        project_info = await get_project_info(
            services=services,
            session_id=session_id
        )

        # Verify we got a valid response
        assert "statistics" in project_info
        assert "relationships_created" in project_info["statistics"]

        reported_count = project_info["statistics"]["relationships_created"]

        # Query actual relationship count from database
        actual_count = await storage.count_records(
            table_name="graph_relationships",
            project_id="test_project"
        )

        # Verify counts match (AC-1.1)
        assert reported_count == actual_count, (
            f"Relationship count mismatch: get_project_info reported {reported_count}, "
            f"but database contains {actual_count} relationships"
        )

        # Also verify that we actually created some relationships
        # (This ensures the test is actually testing something meaningful)
        assert actual_count > 0, (
            "No relationships were created during indexing. "
            "Test may not be exercising the code properly."
        )

    finally:
        # Cleanup
        await event_system.stop(timeout=2.0)
        await memory_system.shutdown()
        await storage.close()


@pytest.mark.asyncio
async def test_relationship_count_matches_after_multiple_indexing_operations(
    tmp_path: Path,
    sample_python_code_with_relationships: Path
):
    """Test that relationship count remains accurate across multiple indexing operations.

    This test verifies that the relationship count stays accurate even when:
    - Files are indexed multiple times (updates)
    - Multiple indexing operations occur

    Requirements: FR-1.1, AC-1.1
    """
    # Create config with temp storage and events enabled
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path / "storage"),
        default_project_id="test_project",
        backend="lancedb",
        event_store=EventStoreConfig(path="test_events.db")
    )
    config.events = EventsConfig(
        enabled=True,
        queue_max_size=100,
        batch_size=10,
        flush_interval_seconds=0.1,
    )

    # Initialize services
    db_manager = LanceDBManager.from_config(config)
    storage = await StorageFacade.from_config(config, project_id="test_project")
    event_system = await EventSystem.from_config(config, project_id="test_project")

    try:
        # Create embedding registry
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())

        # Create indexing pipeline
        indexing_pipeline = IndexingPipeline(
            db_manager=db_manager,
            config=config,
            project_id="test_project",
            event_system=event_system,
            registry=registry,
            project_root=str(sample_python_code_with_relationships)
        )

        # Create session manager
        session_manager = SessionManager(
            db_manager=storage,
            config=config,
            event_system=event_system
        )

        # Create memory system
        from agent_vault.memory.system import MemorySystem
        from agent_vault.embeddings.service import EmbeddingService

        embedding_service = EmbeddingService(config)
        memory_system = MemorySystem(config, embedding_service, event_system=event_system)
        await memory_system.initialize()

        # Create session
        session = await session_manager.create_session(
            project_id="test_project",
            description="Test session for multiple indexing operations"
        )
        session_id = session["session_id"]

        # Services dict
        services = {
            "session_manager": session_manager,
            "storage": storage,
            "memory_system": memory_system
        }

        # Perform first indexing
        await indexing_pipeline.index_directory(
            path=str(sample_python_code_with_relationships),
            wait=True
        )

        # Wait a bit for event persistence
        await asyncio.sleep(0.5)

        # Get count after first indexing
        project_info_1 = await get_project_info(services, session_id)
        reported_count_1 = project_info_1["statistics"]["relationships_created"]
        actual_count_1 = await storage.count_records(
            table_name="graph_relationships",
            project_id="test_project"
        )

        assert reported_count_1 == actual_count_1, (
            f"First indexing: count mismatch (reported={reported_count_1}, actual={actual_count_1})"
        )

        # Perform second indexing (re-index same files)
        await indexing_pipeline.index_directory(
            path=str(sample_python_code_with_relationships),
            wait=True
        )

        # Wait for event persistence
        await asyncio.sleep(0.5)

        # Get count after second indexing
        project_info_2 = await get_project_info(services, session_id)
        reported_count_2 = project_info_2["statistics"]["relationships_created"]
        actual_count_2 = await storage.count_records(
            table_name="graph_relationships",
            project_id="test_project"
        )

        assert reported_count_2 == actual_count_2, (
            f"Second indexing: count mismatch (reported={reported_count_2}, actual={actual_count_2})"
        )

        # Verify that counts are still valid
        assert actual_count_2 > 0, "Should still have relationships after re-indexing"

    finally:
        # Cleanup
        await event_system.stop(timeout=2.0)
        await memory_system.shutdown()
        await storage.close()
