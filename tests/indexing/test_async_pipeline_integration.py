"""Integration tests for async IndexingPipeline operations.

This test suite verifies:
1. End-to-end async indexing with cache and database operations
2. Concurrent document processing with semaphore control
3. No event loop blocking during I/O operations
4. Performance improvements from async operations

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5
"""

import pytest

pytestmark = pytest.mark.integration

import asyncio
import time
from typing import List
import uuid

import pytest
import pytest_asyncio

from agentic_inquiry.config import Config, StorageConfig
from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.embeddings.registry import EmbeddingRegistry
from agentic_inquiry.indexing.pipeline import IndexingPipeline
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager


class HashingEmbedder(Embedder):
    """Simple embedder for testing."""

    def __init__(self):
        self._ndims = 128

    def generate(self, texts: List[str]) -> List[List[float]]:
        """Generate deterministic embeddings based on text hash."""
        return [[float(hash(text) % 100) / 100.0] * self._ndims for text in texts]

    def ndims(self):
        return self._ndims


@pytest_asyncio.fixture
async def mock_db_manager(tmp_path):
    """Create an in-memory database manager."""
    db_uri = f"memory://test_{uuid.uuid4().hex[:8]}"
    manager = InMemoryLanceDBManager(uri=db_uri)
    await manager.connect()
    yield manager
    # Cleanup is handled by in-memory database


@pytest_asyncio.fixture
def mock_embedding_registry():
    """Create an embedding registry with test embedder."""
    registry = EmbeddingRegistry()
    registry.configure_default_embedder(HashingEmbedder(), ndims=128)
    return registry


@pytest_asyncio.fixture
async def pipeline(mock_db_manager, tmp_path, mock_embedding_registry):
    """Create an IndexingPipeline instance."""
    from agentic_inquiry.events import EventSystem
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    project_id = f"test_{uuid.uuid4().hex[:8]}"
    
    # Create EventSystem for the pipeline
    event_system = await EventSystem.from_config(config, project_id=project_id)
    
    try:
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id=project_id,
            registry=mock_embedding_registry,
            max_concurrent=10,
            event_system=event_system,
        )
        yield pipeline
    finally:
        await event_system.stop()


def create_test_document(file_path: str, num_chunks: int = 5) -> ParsedDocument:
    """Create a test document with specified number of chunks."""
    chunks = []
    for i in range(num_chunks):
        chunk = ParserChunk(
            content=f"Test content for chunk {i} in {file_path}",
            fts_text=f"Test content for chunk {i} in {file_path}",
            symbols=[f"test_function_{i}"],
            language="python",
            line_start=i * 10,
            line_end=(i + 1) * 10,
            symbol_metadata={
                f"test_function_{i}": {
                    "type": "function",
                    "is_exported": True,
                }
            },
        )
        chunks.append(chunk)
    
    return ParsedDocument(
        doc_id=f"doc_{file_path}",
        file_path=file_path,
        chunks=chunks,
    )


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_end_to_end_async_indexing(pipeline):
    """Test end-to-end async indexing with cache and database operations.

    Requirement: 15.1 - End-to-end async indexing
    """
    # Create test document
    doc = create_test_document("test_file.py", num_chunks=3)
    
    # Process document
    await pipeline.process_document(doc)
    
    # Verify chunks were indexed
    chunks = await pipeline.db_manager.advanced_filter(
        "document_chunks",
        filters={"file_path": "test_file.py"}
    )
    assert len(chunks) == 3
    
    # Verify entities were indexed
    entities = await pipeline.db_manager.advanced_filter(
        "graph_entities",
        filters={"file_path": "test_file.py"}
    )
    # Expect: 1 file entity + 3 code entities (one per symbol)
    assert len(entities) >= 3
    code_entities = [e for e in entities if e.get("type") not in ("file", "code_module")]
    assert len(code_entities) == 3


async def _process_concurrently(pipeline, num_docs: int) -> float:
    """Process num_docs three-chunk documents concurrently; return seconds taken."""
    docs = [
        create_test_document(f"test_file_{i}.py", num_chunks=3)
        for i in range(num_docs)
    ]
    start_time = time.time()
    await asyncio.gather(*[pipeline.process_document(doc) for doc in docs])
    return time.time() - start_time


@pytest.mark.asyncio
async def test_concurrent_document_processing(pipeline):
    """Test concurrent document processing with semaphore control.
    
    Requirement: 15.2 - Concurrent document processing
    """
    num_docs = 20
    await _process_concurrently(pipeline, num_docs)

    # Verify all documents were processed
    for i in range(num_docs):
        chunks = await pipeline.db_manager.advanced_filter(
            "document_chunks",
            filters={"file_path": f"test_file_{i}.py"}
        )
        assert len(chunks) == 3


@pytest.mark.perf
@pytest.mark.asyncio
async def test_concurrent_document_processing_time_budget(pipeline):
    """Twenty documents under a semaphore of 10 finish well within 30 seconds."""
    duration = await _process_concurrently(pipeline, num_docs=20)

    assert duration < 30.0, f"Processing took too long: {duration:.2f}s"


@pytest.mark.asyncio
async def test_no_event_loop_blocking(pipeline):
    """Test that async operations don't block the event loop.
    
    Requirement: 15.3 - No event loop blocking
    """
    # Create a test document
    doc = create_test_document("test_file.py", num_chunks=5)
    
    # Track if event loop remains responsive during processing
    loop_responsive = []
    
    async def check_loop_responsiveness():
        """Periodically check if event loop is responsive."""
        for _ in range(10):
            await asyncio.sleep(0.01)  # 10ms intervals
            loop_responsive.append(time.time())
    
    # Run document processing and responsiveness check concurrently
    await asyncio.gather(
        pipeline.process_document(doc),
        check_loop_responsiveness()
    )
    
    # Verify event loop remained responsive
    # If loop was blocked, we wouldn't get 10 timestamps
    assert len(loop_responsive) >= 8, \
        f"Event loop was blocked, only {len(loop_responsive)} checks completed"
    
    # Verify timestamps are reasonably spaced (not all at once)
    if len(loop_responsive) >= 2:
        time_diffs = [
            loop_responsive[i+1] - loop_responsive[i]
            for i in range(len(loop_responsive) - 1)
        ]
        avg_diff = sum(time_diffs) / len(time_diffs)
        # Should be around 10ms, allow some variance
        assert 0.005 < avg_diff < 0.05, \
            f"Unexpected timing pattern: avg={avg_diff:.3f}s"


@pytest.mark.asyncio
async def test_concurrent_processing_with_cache(pipeline, tmp_path):
    """Test concurrent processing with async cache operations.
    
    Requirement: 12.5 - Async cache operations in pipeline
    """
    from agentic_inquiry.cache import register_cache, DocumentCache
    
    # Create and register a cache
    cache = DocumentCache(max_size=100)
    register_cache("test_cache", cache)
    
    # Create pipeline with cache
    from agentic_inquiry.events import EventSystem
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    project_id = f"test_{uuid.uuid4().hex[:8]}"
    
    registry = EmbeddingRegistry()
    registry.configure_default_embedder(HashingEmbedder(), ndims=128)
    
    # Create EventSystem for the pipeline
    event_system = await EventSystem.from_config(config, project_id=project_id)
    
    try:
        pipeline_with_cache = IndexingPipeline(
            db_manager=pipeline.db_manager,
            config=config,
            project_id=project_id,
            registry=registry,
            cache_name="test_cache",
            max_concurrent=5,
            event_system=event_system,
        )
    
        # Use actual sample files from tests/parsers/samples
        sample_files = [
            "tests/parsers/samples/test.py",
            "tests/parsers/samples/test.js",
            "tests/parsers/samples/cache_test_0.py",
            "tests/parsers/samples/cache_test_1.py",
            "tests/parsers/samples/cache_test_2.py",
        ]
        
        # Create test documents using actual file paths
        docs = [
            create_test_document(file_path, num_chunks=2)
            for file_path in sample_files
        ]
        
        # Process documents concurrently (should cache them)
        tasks = [pipeline_with_cache.process_document(doc) for doc in docs]
        await asyncio.gather(*tasks)
        
        # Verify cache was populated
        for file_path in sample_files:
            cached_doc = await pipeline_with_cache.get_cached_document(file_path)
            assert cached_doc is not None, f"Cache miss for {file_path}"
            assert cached_doc.file_path == file_path
    finally:
        await event_system.stop()


@pytest.mark.asyncio
async def test_performance_improvement(pipeline):
    """Test that async implementation provides performance improvement.
    
    Requirement: 15.4, 15.5 - Performance validation
    """
    # Create test documents
    num_docs = 50
    docs = [
        create_test_document(f"perf_test_{i}.py", num_chunks=2)
        for i in range(num_docs)
    ]
    
    # Measure concurrent processing time
    start_time = time.time()
    tasks = [pipeline.process_document(doc) for doc in docs]
    await asyncio.gather(*tasks)
    concurrent_duration = time.time() - start_time
    
    print("\nPerformance test results:")
    print(f"  Documents: {num_docs}")
    print(f"  Concurrent duration: {concurrent_duration:.2f}s")
    print(f"  Throughput: {num_docs / concurrent_duration:.1f} docs/sec")
    
    # Verify all documents were processed
    total_chunks = 0
    for i in range(num_docs):
        chunks = await pipeline.db_manager.advanced_filter(
            "document_chunks",
            filters={"file_path": f"perf_test_{i}.py"}
        )
        total_chunks += len(chunks)
    
    assert total_chunks == num_docs * 2, \
        f"Expected {num_docs * 2} chunks, got {total_chunks}"
    
    # Sanity check: should process at reasonable speed
    # With async and concurrency, should be able to process many docs per second
    throughput = num_docs / concurrent_duration
    assert throughput > 5.0, \
        f"Throughput too low: {throughput:.1f} docs/sec"


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency(pipeline):
    """Test that semaphore properly limits concurrent operations.
    
    Requirement: 11.5 - Concurrency control
    """
    # Track concurrent operations
    concurrent_count = 0
    max_concurrent = 0
    lock = asyncio.Lock()
    
    # Monkey-patch the implementation to track concurrency
    original_impl = pipeline._process_document_impl

    async def tracked_impl(doc, flush_relationships=True):
        nonlocal concurrent_count, max_concurrent
        async with lock:
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)

        try:
            # Add a small delay to make concurrency visible
            await asyncio.sleep(0.01)
            await original_impl(doc, flush_relationships)
        finally:
            async with lock:
                concurrent_count -= 1

    pipeline._process_document_impl = tracked_impl
    
    # Create many documents
    docs = [
        create_test_document(f"concurrent_test_{i}.py", num_chunks=1)
        for i in range(30)
    ]
    
    # Process concurrently
    tasks = [pipeline.process_document(doc) for doc in docs]
    await asyncio.gather(*tasks)
    
    # Verify semaphore limited concurrency
    print("\nConcurrency test results:")
    print(f"  Max concurrent operations: {max_concurrent}")
    print("  Semaphore limit: 10")
    
    # Should not exceed semaphore limit
    assert max_concurrent <= 10, \
        f"Exceeded semaphore limit: {max_concurrent} > 10"
    
    # Should have some concurrency (not purely sequential)
    assert max_concurrent >= 2, \
        f"No concurrency detected: {max_concurrent}"
