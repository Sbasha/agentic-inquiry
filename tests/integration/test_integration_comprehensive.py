"""Comprehensive integration tests for agentic-inquiry system."""

import pytest

pytestmark = pytest.mark.integration

import tempfile
from pathlib import Path
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from agentic_inquiry.config import Config, StorageConfig


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


from agentic_inquiry.database.lancedb_manager import LanceDBManager
from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter
from agentic_inquiry.storage.facade import StorageFacade
from agentic_inquiry.indexing.pipeline import IndexingPipeline
from agentic_inquiry.search.service import SearchService

# Trigger parser auto-registration
import agentic_inquiry.parsers.implementations  # noqa: F401

@pytest.fixture
def temp_project_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)
        (project_path / "module_a.py").write_text("""
def calculate_sum(a: int, b: int) -> int:
    return a + b

class Calculator:
    def add(self, x: int, y: int) -> int:
        return calculate_sum(x, y)
""")
        (project_path / "module_b.py").write_text("""
from module_a import Calculator

def process_data(values: list) -> int:
    calc = Calculator()
    total = 0
    for val in values:
        total = calc.add(total, val)
    return total
""")
        yield project_path


@pytest_asyncio.fixture
async def test_config_with_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_root = Path(tmpdir) / "storage"
        storage_root.mkdir()
        config = Config(
            storage=StorageConfig(
                root=str(storage_root),
                default_project_id="test_project"
            )
        )
        yield config


@pytest_asyncio.fixture
async def mock_embedding_registry():
    from agentic_inquiry.embeddings.registry import EmbeddingRegistry
    
    class _DummyEmbedder:
        def generate(self, texts):
            return [[0.1] * 384 for _ in texts]
        def ndims(self):
            return 384
    
    return EmbeddingRegistry(default_embedder=_DummyEmbedder())


@pytest_asyncio.fixture
async def mock_db_manager(test_config_with_db):
    async with LanceDBManager.from_config(test_config_with_db) as manager:
        yield manager


@pytest_asyncio.fixture
async def indexing_pipeline_fixture(mock_db_manager, test_config_with_db, mock_embedding_registry, temp_project_root):
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=test_config_with_db,
        project_id="test_project",
        registry=mock_embedding_registry,
        project_root=str(temp_project_root),
    )
    return pipeline



@pytest.mark.asyncio
class TestIndexingPipelineIntegration:
    
    async def test_complete_indexing_flow(self, indexing_pipeline_fixture, temp_project_root, mock_db_manager):
        from agentic_inquiry.parsers.executor import get_parser_instance, execute_parser
        
        pipeline = indexing_pipeline_fixture
        python_files = list(temp_project_root.glob("*.py"))
        assert len(python_files) == 2
        
        parser = get_parser_instance("unified_code")
        for file_path in python_files:
            parsed_doc = await execute_parser(parser, str(file_path))
            await pipeline.process_document(parsed_doc)
        
        symbol_count = pipeline.symbol_registry.get_symbol_count()
        assert symbol_count > 0
        
        stats = pipeline.symbol_registry.get_statistics()
        assert stats["symbol_count"] > 0
        # On macOS, /var -> /private/var symlink can cause path doubling
        assert stats["file_count"] >= 2
        
        chunks = await mock_db_manager.advanced_filter(
            table_name="document_chunks",
            filters={"project_id": "test_project"},
            limit=100
        )
        assert len(chunks) > 0
        
        for chunk in chunks:
            assert "id" in chunk
            assert "content" in chunk
            assert "project_id" in chunk
            assert chunk["project_id"] == "test_project"


@pytest.mark.asyncio
class TestHybridSearchIntegration:
    
    async def test_hybrid_search_end_to_end(self, indexing_pipeline_fixture, temp_project_root, mock_db_manager, test_config_with_db, mock_embedding_registry):
        from agentic_inquiry.parsers.executor import get_parser_instance, execute_parser
        
        pipeline = indexing_pipeline_fixture
        parser = get_parser_instance("unified_code")
        for file_path in temp_project_root.glob("*.py"):
            parsed_doc = await execute_parser(parser, str(file_path))
            await pipeline.process_document(parsed_doc)
        
        adapter = LanceDBAdapter(mock_db_manager)
        facade = StorageFacade(
            config=test_config_with_db,
            project_id="test_project",
            vector_provider=adapter,
            graph_provider=adapter,
        )
        search_service = SearchService(storage=facade, config=test_config_with_db)
        
        # Use the embedder directly from the registry's private attribute
        embedder = mock_embedding_registry._default_embedder
        query_vector = embedder.generate(["calculator"])[0]
        
        results = await search_service.hybrid_search(
            query_vector=query_vector,
            query_fts="calculator",
            limit=10,
            rerank_by_graph=False
        )
        
        assert len(results) > 0



@pytest.mark.asyncio
class TestMultiProjectIntegration:
    
    async def test_multi_project_isolation(self, temp_project_root, test_config_with_db, mock_embedding_registry):
        from agentic_inquiry.parsers.executor import get_parser_instance, execute_parser

        # Use the same db manager but different project_ids for isolation
        mock_event_system = _create_mock_event_system()
        project_root = str(temp_project_root)
        async with LanceDBManager.from_config(test_config_with_db) as mock_db_manager:
            pipeline1 = IndexingPipeline(db_manager=mock_db_manager, config=test_config_with_db, project_id="project1", event_system=mock_event_system, registry=mock_embedding_registry, project_root=project_root)
            pipeline2 = IndexingPipeline(db_manager=mock_db_manager, config=test_config_with_db, project_id="project2", event_system=mock_event_system, registry=mock_embedding_registry, project_root=project_root)
            
            parser = get_parser_instance("unified_code")
            file_path = temp_project_root / "module_a.py"
            parsed_doc = await execute_parser(parser, str(file_path))
            await pipeline1.process_document(parsed_doc)
            await pipeline2.process_document(parsed_doc)
            
            chunks1 = await mock_db_manager.advanced_filter(table_name="document_chunks", filters={"project_id": "project1"}, limit=100, project_id=None)
            chunks2 = await mock_db_manager.advanced_filter(table_name="document_chunks", filters={"project_id": "project2"}, limit=100, project_id=None)
            
            assert len(chunks1) > 0
            assert len(chunks2) > 0
            
            for chunk in chunks1:
                assert chunk["project_id"] == "project1"
            for chunk in chunks2:
                assert chunk["project_id"] == "project2"


class TestConfigurationIntegration:

    def test_config_with_default_project_id(self, tmp_path):
        """Test Config stores default_project_id correctly."""
        config = Config(storage=StorageConfig(root=str(tmp_path), default_project_id="my_project"))
        assert config.storage.default_project_id == "my_project"

    def test_config_without_default_project_id(self, tmp_path):
        """Test Config allows None for default_project_id."""
        config = Config(storage=StorageConfig(root=str(tmp_path), default_project_id=None))
        assert config.storage.default_project_id is None

    def test_config_storage_root_path(self, tmp_path):
        """Test Config stores storage root path correctly."""
        config = Config(storage=StorageConfig(root=str(tmp_path), default_project_id="test_proj"))
        assert config.storage.root == str(tmp_path)


@pytest.mark.asyncio
class TestIntegrationPerformance:
    
    @pytest.mark.perf
    async def test_indexing_performance(self, indexing_pipeline_fixture, temp_project_root):
        from agentic_inquiry.parsers.executor import get_parser_instance, execute_parser
        
        start_time = time.time()
        pipeline = indexing_pipeline_fixture
        parser = get_parser_instance("unified_code")
        
        for file_path in temp_project_root.glob("*.py"):
            parsed_doc = await execute_parser(parser, str(file_path))
            await pipeline.process_document(parsed_doc)
        
        elapsed_time = time.time() - start_time
        assert elapsed_time < 3.0, f"Indexing took {elapsed_time:.2f}s"
