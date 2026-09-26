"""Fixtures for contract tests.

This module provides parameterized fixtures for testing multiple provider
implementations against the same contract tests.

Each provider is initialized, used for tests, and then cleaned up.

Supported providers:
- memory: In-memory provider (always available)
- lancedb: LanceDB file-based provider (always available)
"""

import uuid

import pytest
import pytest_asyncio

from agentic_inquiry.config import Config, StorageConfig
from agentic_inquiry.storage.providers import InMemoryProvider, LanceDBProvider


def generate_project_id() -> str:
    """Generate a unique project ID for test isolation."""
    return f"contract_test_{uuid.uuid4().hex[:8]}"


# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture
def test_config(tmp_path):
    """Create test configuration with temporary storage."""
    storage_config = StorageConfig(
        root=str(tmp_path / "storage"),
    )
    config = Config(storage=storage_config)
    config.storage.default_project_id = generate_project_id()
    return config


@pytest.fixture
def project_id():
    """Generate unique project ID for each test."""
    return generate_project_id()


# =============================================================================
# Provider Fixtures - InMemory
# =============================================================================


@pytest_asyncio.fixture
async def memory_provider(project_id):
    """Create and initialize an in-memory provider."""
    provider = InMemoryProvider(project_id=project_id)
    await provider.initialize()
    yield provider
    await provider.close()


# =============================================================================
# Provider Fixtures - LanceDB
# =============================================================================


@pytest_asyncio.fixture
async def lancedb_provider(test_config, project_id):
    """Create and initialize a LanceDB provider."""
    provider = LanceDBProvider(
        config=test_config,
        project_id=project_id,
    )
    await provider.initialize()
    yield provider
    await provider.close()


# =============================================================================
# Provider Fixtures
# =============================================================================


# =============================================================================
# Parameterized Provider Fixture
# =============================================================================


def _collect_provider_params() -> list[str]:
    """Local providers only."""
    return ["memory", "lancedb"]


@pytest.fixture(params=_collect_provider_params())
def provider_type(request):
    """Parameterized fixture for provider type."""
    return request.param


@pytest_asyncio.fixture
async def vector_provider(provider_type, test_config, project_id):
    """Create a parameterized vector provider.

    This fixture runs the same tests against multiple provider implementations.
    """
    if provider_type == "memory":
        provider = InMemoryProvider(project_id=project_id)
        await provider.initialize()
        yield provider
        await provider.close()

    elif provider_type == "lancedb":
        provider = LanceDBProvider(config=test_config, project_id=project_id)
        await provider.initialize()
        yield provider
        await provider.close()

    else:
        pytest.skip(f"Unknown provider type: {provider_type}")


# =============================================================================
# Test Data Factories
# =============================================================================


@pytest.fixture
def chunk_factory():
    """Factory for creating test DocumentChunks."""
    from agentic_inquiry.models.document_chunk import DocumentChunk

    def _create_chunk(
        chunk_id: str = None,
        project_id: str = "test",
        file_path: str = "/test/file.py",
        content: str = "test content",
        content_type: str = "CODE",
        vector: list = None,
    ):
        if chunk_id is None:
            chunk_id = f"chunk_{uuid.uuid4().hex[:8]}"
        if vector is None:
            vector = [0.1] * 384

        return DocumentChunk(
            id=chunk_id,
            doc_id=f"doc_{chunk_id}",
            project_id=project_id,
            file_path=file_path,
            content=content,
            fts_text=content,  # Use content as FTS text
            content_type=content_type,
            vector=vector,
            line_start=1,
            line_end=10,
            language="python",
        )

    return _create_chunk


@pytest.fixture
def entity_factory():
    """Factory for creating test GraphEntities."""
    from agentic_inquiry.models.graph_entity import EntityType, GraphEntity

    def _create_entity(
        entity_id: str = None,
        project_id: str = "test",
        name: str = "test_entity",
        entity_type: str = EntityType.CODE_FUNCTION.value,
        file_path: str = "/test/file.py",
        vector: list = None,
    ):
        if entity_id is None:
            entity_id = f"entity_{uuid.uuid4().hex[:8]}"
        if vector is None:
            vector = [0.1] * 384

        return GraphEntity(
            id=entity_id,
            project_id=project_id,
            name=name,
            type=entity_type,
            file_path=file_path,
            doc_id=f"doc_{entity_id}",
            vector=vector,
        )

    return _create_entity


@pytest.fixture
def relationship_factory():
    """Factory for creating test GraphRelationships."""
    from agentic_inquiry.models.graph_relationship import (
        GraphRelationship,
        RelationshipType,
    )

    def _create_relationship(
        rel_id: str = None,
        project_id: str = "test",
        source_id: str = "source",
        target_id: str = "target",
        rel_type: str = RelationshipType.CALLS.value,
        vector: list = None,
    ):
        if rel_id is None:
            rel_id = f"rel_{uuid.uuid4().hex[:8]}"
        if vector is None:
            vector = [0.1] * 384

        return GraphRelationship(
            id=rel_id,
            project_id=project_id,
            source_id=source_id,
            target_id=target_id,
            type=rel_type,
            vector=vector,
        )

    return _create_relationship
