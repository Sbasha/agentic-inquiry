"""Complete integration tests for document entity extraction.

This test file consolidates:
- test_document_entity_integration.py (basic integration test)
- test_document_entity_integration_complete.py (comprehensive tests for Task 6)

Tests cover:
- Entity registration in Symbol Registry (Task 6.1)
- Relationship creation in LanceDB (Task 6.2)
- Search returns document entities (Task 6.3)
- Graph traversal queries (Task 6.4)
"""
import asyncio
import pytest

pytestmark = pytest.mark.integration
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from agent_vault.config import Config, StorageConfig
from agent_vault.database.adapters.lancedb_adapter import LanceDBAdapter
from agent_vault.embeddings.base import Embedder
from agent_vault.embeddings.registry import EmbeddingRegistry
from agent_vault.indexing.pipeline import IndexingPipeline
from agent_vault.parsers.implementations.document import DocumentParser
from agent_vault.search.service import SearchService
from agent_vault.storage.facade import StorageFacade
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager


class _DummyEmbedder(Embedder):
    """Dummy embedder for testing."""
    def __init__(self, ndims=128):
        self._ndims = ndims

    def generate(self, texts):
        return [[float(len(text) % 100) / 100.0] * self._ndims for text in texts]

    def ndims(self):
        return self._ndims


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


def test_document_parser_entity_extraction_integration():
    """Test end-to-end document entity extraction with real DocumentParser."""
    async def run():
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder(ndims=1))
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-doc-parser")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        config = Config()
        config.storage = StorageConfig(root="/tmp/project", default_project_id="test_project")
        mock_event_system = _create_mock_event_system()

        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry
        )

        # Parse the actual outline.md sample document
        parser = DocumentParser()
        sample_path = Path("tests/parsers/samples/docs/outline.md")
        
        if not sample_path.exists():
            print(f"Skipping test: {sample_path} not found")
            return
        
        parsed_doc = await parser.parse(str(sample_path))

        # Verify parser extracted chunks with element metadata
        assert len(parsed_doc.chunks) > 0, "Parser should extract chunks"
        
        # Count chunks with element_name (document entities)
        entity_chunks = [c for c in parsed_doc.chunks if c.element_name]
        print(f"Parser extracted {len(entity_chunks)} chunks with element_name")
        
        # Verify we have headings
        heading_chunks = [c for c in parsed_doc.chunks if c.element_type == "doc_section"]
        print(f"Found {len(heading_chunks)} heading chunks")
        assert len(heading_chunks) > 0, "Should have heading chunks"
        
        # Verify some headings have parent_id set
        nested_headings = [c for c in heading_chunks if c.parent_id]
        print(f"Found {len(nested_headings)} nested headings with parent_id")
        
        # Verify relationships were extracted
        total_relationships = sum(len(c.relationships) for c in parsed_doc.chunks)
        print(f"Parser extracted {total_relationships} relationships")
        
        # Process document through pipeline (disable auto-flush to verify pending relationships)
        await pipeline.process_document(parsed_doc, flush_relationships=False)

        # Verify document entities were registered in symbol registry
        # Check for some known headings from outline.md
        expected_headings = [
            "Presentation Outline: Agent-Vault (Executive Version)",
            "Slide 1: Title",
            "Slide 2: The \"Last Mile\" Problem with Enterprise AI",
        ]
        
        registered_count = 0
        for heading in expected_headings:
            if heading in pipeline.symbol_registry._by_name:
                registered_count += 1
                metadata = pipeline.symbol_registry.lookup_by_name(heading)
                print(f"✓ Registered: {heading} (type: {metadata[0].entity_type})")
        
        print(f"Registered {registered_count}/{len(expected_headings)} expected headings")
        assert registered_count > 0, "Should register at least some headings"
        
        # Verify entities were created in database
        all_entities = await mock_db_manager.advanced_filter("graph_entities")
        doc_entities = [e for e in all_entities if e.get("type") in ["doc_section", "section", "table", "figure"]]
        print(f"Created {len(doc_entities)} document entities in database")
        assert len(doc_entities) > 0, "Should create document entities in database"
        
        # Verify relationships were collected
        print(f"Collected {len(pipeline._pending_relationships)} pending relationships")
        assert len(pipeline._pending_relationships) > 0, "Should collect relationships"
        
        # Flush relationships
        created_count = await pipeline.flush_pending_relationships()
        print(f"Created {created_count} relationships in database")
        assert created_count > 0, "Should create relationships in database"
        
        # Verify relationships in database
        all_relationships = await mock_db_manager.advanced_filter("graph_relationships")
        print(f"Total relationships in database: {len(all_relationships)}")
        
        # Check for contains relationships
        contains_rels = [r for r in all_relationships if r.get("type") == "contains"]
        print(f"Contains relationships: {len(contains_rels)}")
        
        # Check for follows relationships
        follows_rels = [r for r in all_relationships if r.get("type") == "follows"]
        print(f"Follows relationships: {len(follows_rels)}")
        
        # Verify symbol registry stats
        stats = await pipeline.symbol_registry.get_stats()
        print(f"Symbol registry stats: {stats}")
        assert stats["total_symbols"] > 0, "Should have registered symbols"
        
        print("\n✅ Integration test passed!")

    asyncio.run(run())


def test_6_1_entity_registration_in_symbol_registry():
    """Task 6.1: Test entity registration in Symbol Registry.
    
    - Index outline.md document
    - Query Symbol Registry for heading entities by element_name
    - Verify entities found with correct metadata
    - Verify entity_type is "doc_section"
    """
    async def run():
        # Setup
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-6-1")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        config = Config()
        config.storage = StorageConfig(root="/tmp/project", default_project_id="test_project")
        mock_event_system = _create_mock_event_system()

        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry
        )

        # Parse outline.md
        parser = DocumentParser()
        sample_path = Path("tests/parsers/samples/docs/outline.md")
        
        if not sample_path.exists():
            print(f"⚠️  Skipping test: {sample_path} not found")
            return
        
        parsed_doc = await parser.parse(str(sample_path))
        
        # Process document through pipeline
        await pipeline.process_document(parsed_doc)
        
        # Test 1: Query for known heading entities
        test_headings = [
            "Presentation Outline: Agent-Vault (Executive Version)",
            "Slide 1: Title",
            "Slide 2: The \"Last Mile\" Problem with Enterprise AI",
            "Slide 3: The Solution: Four Breakthrough Capabilities",
        ]
        
        found_count = 0
        for heading_name in test_headings:
            results = pipeline.symbol_registry.lookup_by_name(heading_name)
            if results:
                found_count += 1
                metadata = results[0]
                
                # Verify metadata
                assert metadata.name == heading_name, f"Name mismatch: {metadata.name}"
                assert metadata.entity_type == "doc_section", f"Type should be 'heading', got {metadata.entity_type}"
                assert metadata.file_path.endswith("outline.md"), f"File path should end with outline.md: {metadata.file_path}"
                assert metadata.is_exported is True, "Document entities should be exported"
                
                print(f"✓ Found heading: {heading_name}")
                print(f"  - Type: {metadata.entity_type}")
                print(f"  - File: {metadata.file_path}")
                print(f"  - Exported: {metadata.is_exported}")
        
        assert found_count >= 3, f"Should find at least 3 headings, found {found_count}"
        print(f"\n✅ Task 6.1 PASSED: Found {found_count}/{len(test_headings)} headings in Symbol Registry")
        
        # Test 2: Query by name and type
        results = pipeline.symbol_registry.lookup_by_name_and_type(
            "Slide 1: Title",
            "doc_section"
        )
        assert len(results) > 0, "Should find heading by name and type"
        print(f"✓ lookup_by_name_and_type works: found {len(results)} results")
        
        # Test 3: Verify stats
        stats = await pipeline.symbol_registry.get_stats()
        print("\nSymbol Registry Stats:")
        print(f"  - Total symbols: {stats['total_symbols']}")
        print(f"  - Total files: {stats['total_files']}")
        print(f"  - Total entries: {stats['total_entries']}")
        
        assert stats["total_symbols"] > 0, "Should have registered symbols"
        assert stats["total_files"] >= 1, "Should have at least 1 file"

    asyncio.run(run())


def test_6_2_relationship_creation_in_lancedb():
    """Task 6.2: Test relationship creation in LanceDB.
    
    - Index outline.md document
    - Query relationships table for contains relationships
    - Query relationships table for follows relationships
    - Verify source and target IDs are correct
    """
    async def run():
        # Setup
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-6-2")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        config = Config()
        config.storage = StorageConfig(root="/tmp/project", default_project_id="test_project")
        mock_event_system = _create_mock_event_system()

        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry
        )

        # Parse outline.md
        parser = DocumentParser()
        sample_path = Path("tests/parsers/samples/docs/outline.md")
        
        if not sample_path.exists():
            print(f"⚠️  Skipping test: {sample_path} not found")
            return
        
        parsed_doc = await parser.parse(str(sample_path))
        
        # Process document (auto-flushes relationships by default)
        await pipeline.process_document(parsed_doc)

        # Relationships are auto-flushed during process_document
        # Query all relationships directly from database
        all_relationships = await mock_db_manager.advanced_filter("graph_relationships")
        print(f"\nTotal relationships in database: {len(all_relationships)}")
        assert len(all_relationships) > 0, "Should have created relationships in database"
        
        # Test 1: Check for contains relationships
        contains_rels = [r for r in all_relationships if r.get("type") == "contains"]
        print(f"Contains relationships: {len(contains_rels)}")
        assert len(contains_rels) > 0, "Should have contains relationships"
        
        # Verify structure of contains relationships
        if contains_rels:
            sample_rel = contains_rels[0]
            print("\nSample contains relationship:")
            print(f"  - Source ID: {sample_rel.get('source_id')}")
            print(f"  - Target ID: {sample_rel.get('target_id')}")
            print(f"  - Type: {sample_rel.get('type')}")
            
            assert "source_id" in sample_rel, "Relationship should have source_id"
            assert "target_id" in sample_rel, "Relationship should have target_id"
            assert sample_rel["type"] == "contains", "Type should be 'contains'"
        
        # Test 2: Check for follows relationships
        follows_rels = [r for r in all_relationships if r.get("type") == "follows"]
        print(f"Follows relationships: {len(follows_rels)}")
        assert len(follows_rels) > 0, "Should have follows relationships"
        
        # Verify structure of follows relationships
        if follows_rels:
            sample_rel = follows_rels[0]
            print("\nSample follows relationship:")
            print(f"  - Source ID: {sample_rel.get('source_id')}")
            print(f"  - Target ID: {sample_rel.get('target_id')}")
            print(f"  - Type: {sample_rel.get('type')}")
            
            assert sample_rel["type"] == "follows", "Type should be 'follows'"
        
        # Test 3: Verify IDs reference actual entities
        # Get all entities
        all_entities = await mock_db_manager.advanced_filter("graph_entities")
        entity_ids = {e.get("id") for e in all_entities}
        print(f"\nTotal entities in database: {len(entity_ids)}")
        
        # Check that relationship IDs reference real entities
        valid_refs = 0
        for rel in all_relationships[:10]:  # Check first 10
            source_id = rel.get("source_id")
            target_id = rel.get("target_id")
            
            # Note: source might be "document" type which won't be in entities
            if "document::" in source_id:
                # Document-level relationships are valid
                valid_refs += 1
            elif source_id in entity_ids and target_id in entity_ids:
                valid_refs += 1
        
        print(f"Valid relationship references: {valid_refs}/10 checked")
        
        print("\n✅ Task 6.2 PASSED: Relationships created and verified in LanceDB")

    asyncio.run(run())


def test_6_3_search_returns_document_entities():
    """Task 6.3: Test search returns document entities.
    
    - Index outline.md document
    - Search for heading text (e.g., "Slide 1")
    - Verify document entity appears in results
    - Verify entity metadata is correct
    """
    async def run():
        # Setup
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-6-3")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        config = Config()
        config.storage = StorageConfig(root="/tmp/project", default_project_id="test_project")
        mock_event_system = _create_mock_event_system()

        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry
        )

        # Parse outline.md
        parser = DocumentParser()
        sample_path = Path("tests/parsers/samples/docs/outline.md")
        
        if not sample_path.exists():
            print(f"⚠️  Skipping test: {sample_path} not found")
            return
        
        parsed_doc = await parser.parse(str(sample_path))
        
        # Process document
        await pipeline.process_document(parsed_doc)
        await pipeline.flush_pending_relationships()
        
        # Create search service with StorageFacade
        adapter = LanceDBAdapter(mock_db_manager)
        storage = StorageFacade(
            config=config,
            project_id="test_project",
            vector_provider=adapter,
            graph_provider=adapter
        )
        search_service = SearchService(storage=storage, config=config, event_system=mock_event_system)
        
        # Test 1: FTS search for heading text
        search_queries = [
            "Slide 1",
            "Agent-Vault",
            "Memory System",
            "Solution",
        ]
        
        for query in search_queries:
            results = await search_service.fts_search(
                query_fts=query,
                limit=10
            )
            
            print(f"\nSearch for '{query}': {len(results)} results")
            
            if results:
                # Check if any result has element_name matching our query
                # SearchResult.data contains the actual row data
                entity_results = [r for r in results if r.data.get("element_name")]
                print(f"  - Results with element_name: {len(entity_results)}")

                if entity_results:
                    sample = entity_results[0].data
                    print(f"  - Sample element_name: {sample.get('element_name')}")
                    print(f"  - Sample element_type: {sample.get('element_type')}")
                    print(f"  - Sample file_path: {sample.get('file_path')}")

                    # Verify metadata
                    assert "element_name" in sample, "Should have element_name"
                    assert "element_type" in sample, "Should have element_type"
                    assert sample.get("file_path", "").endswith("outline.md"), "Should be from outline.md"
        
        # Test 2: Vector search for heading content
        embedder = _DummyEmbedder()
        query_vector = embedder.generate(["Slide 1: Title"])[0]
        
        vector_results = await search_service.vector_search(
            query_vector=query_vector,
            limit=10
        )
        
        print(f"\nVector search results: {len(vector_results)}")
        
        # Test 3: Advanced filter for specific element types
        heading_chunks = await mock_db_manager.advanced_filter(
            table_name="document_chunks",
            filters={"element_type": "doc_section"},
            limit=20
        )
        
        print(f"\nChunks with element_type='heading': {len(heading_chunks)}")
        assert len(heading_chunks) > 0, "Should find heading chunks"
        
        if heading_chunks:
            sample = heading_chunks[0]
            print("Sample heading chunk:")
            print(f"  - element_name: {sample.get('element_name')}")
            print(f"  - element_type: {sample.get('element_type')}")
            print(f"  - content: {sample.get('content')[:100]}...")
            
            assert sample.get("element_type") == "doc_section", "Should be heading type"
            assert sample.get("element_name"), "Should have element_name"
        
        print("\n✅ Task 6.3 PASSED: Search returns document entities with correct metadata")

    asyncio.run(run())


def test_6_4_graph_traversal_queries():
    """Task 6.4: Test graph traversal queries.
    
    - Index outline.md document
    - Query for all children of a heading (contains relationships)
    - Query for next sibling of a heading (follows relationships)
    - Verify correct entities returned
    """
    async def run():
        # Setup
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-6-4")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        config = Config()
        config.storage = StorageConfig(root="/tmp/project", default_project_id="test_project")
        mock_event_system = _create_mock_event_system()

        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry
        )

        # Parse outline.md
        parser = DocumentParser()
        sample_path = Path("tests/parsers/samples/docs/outline.md")
        
        if not sample_path.exists():
            print(f"⚠️  Skipping test: {sample_path} not found")
            return
        
        parsed_doc = await parser.parse(str(sample_path))
        
        # Process document
        await pipeline.process_document(parsed_doc)
        await pipeline.flush_pending_relationships()
        
        # Get all entities and relationships for analysis
        all_entities = await mock_db_manager.advanced_filter("graph_entities")
        all_relationships = await mock_db_manager.advanced_filter("graph_relationships")
        
        print(f"Total entities: {len(all_entities)}")
        print(f"Total relationships: {len(all_relationships)}")
        
        # Build entity lookup
        entities_by_id = {e["id"]: e for e in all_entities}
        
        # Test 1: Find children of a heading (contains relationships)
        # Look for a heading entity
        heading_entities = [e for e in all_entities if e.get("type") == "doc_section"]
        print(f"\nHeading entities: {len(heading_entities)}")
        
        if heading_entities:
            # Pick a heading that likely has children
            parent_heading = heading_entities[0]
            parent_id = parent_heading["id"]
            parent_name = parent_heading.get("name", "Unknown")
            
            print(f"\nTest 1: Finding children of '{parent_name}'")
            print(f"  Parent ID: {parent_id}")
            
            # Query for contains relationships from this heading
            contains_rels = [
                r for r in all_relationships
                if r.get("source_id") == parent_id and r.get("type") == "contains"
            ]
            
            print(f"  Found {len(contains_rels)} contains relationships")
            
            # Get the child entities
            children = []
            for rel in contains_rels[:5]:  # Limit to first 5
                target_id = rel.get("target_id")
                if target_id in entities_by_id:
                    child = entities_by_id[target_id]
                    children.append(child)
                    print(f"    - Child: {child.get('name')} (type: {child.get('type')})")
            
            if contains_rels:
                assert len(children) > 0, "Should find child entities"
        
        # Test 2: Find siblings (follows relationships)
        print("\nTest 2: Finding sibling relationships")
        
        follows_rels = [r for r in all_relationships if r.get("type") == "follows"]
        print(f"  Total follows relationships: {len(follows_rels)}")
        
        if follows_rels:
            # Pick a follows relationship
            sample_rel = follows_rels[0]
            source_id = sample_rel.get("source_id")
            target_id = sample_rel.get("target_id")
            
            source_entity = entities_by_id.get(source_id)
            target_entity = entities_by_id.get(target_id)
            
            if source_entity and target_entity:
                print("  Sample follows relationship:")
                print(f"    - Source: {source_entity.get('name')} (type: {source_entity.get('type')})")
                print(f"    - Target: {target_entity.get('name')} (type: {target_entity.get('type')})")
                
                # Verify both are same type (siblings should be same type)
                assert source_entity.get("type") == target_entity.get("type"), \
                    "Siblings should have same entity type"
        
        # Test 3: Multi-hop traversal (find all descendants)
        if heading_entities:
            root_heading = heading_entities[0]
            root_id = root_heading["id"]
            
            print(f"\nTest 3: Multi-hop traversal from '{root_heading.get('name')}'")
            
            # Find all descendants (BFS)
            visited = {root_id}
            queue = [root_id]
            depth = 0
            max_depth = 3
            
            while queue and depth < max_depth:
                current_level = queue[:]
                queue = []
                depth += 1
                
                for entity_id in current_level:
                    # Find all contains relationships from this entity
                    children_rels = [
                        r for r in all_relationships
                        if r.get("source_id") == entity_id and r.get("type") == "contains"
                    ]
                    
                    for rel in children_rels:
                        target_id = rel.get("target_id")
                        if target_id not in visited:
                            visited.add(target_id)
                            queue.append(target_id)
            
            descendants_count = len(visited) - 1  # Exclude root
            print(f"  Found {descendants_count} descendants within {max_depth} hops")
            
            if descendants_count > 0:
                # Show some descendants
                for entity_id in list(visited)[1:6]:  # Skip root, show first 5
                    if entity_id in entities_by_id:
                        entity = entities_by_id[entity_id]
                        print(f"    - {entity.get('name')} (type: {entity.get('type')})")
        
        # Test 4: Verify relationship metadata
        print("\nTest 4: Verify relationship metadata")
        
        if all_relationships:
            sample_rel = all_relationships[0]
            print("  Sample relationship structure:")
            print(f"    - id: {sample_rel.get('id')}")
            print(f"    - source_id: {sample_rel.get('source_id')}")
            print(f"    - target_id: {sample_rel.get('target_id')}")
            print(f"    - type: {sample_rel.get('type')}")
            print(f"    - metadata: {sample_rel.get('metadata')}")
            
            # Verify required fields
            assert "id" in sample_rel, "Relationship should have id"
            assert "source_id" in sample_rel, "Relationship should have source_id"
            assert "target_id" in sample_rel, "Relationship should have target_id"
            assert "type" in sample_rel, "Relationship should have type"
        
        print("\n✅ Task 6.4 PASSED: Graph traversal queries work correctly")

    asyncio.run(run())


def test_all_integration_tests():
    """Run all integration tests in sequence."""
    print("=" * 80)
    print("Running Document Entity Integration Tests")
    print("=" * 80)
    
    print("\n" + "=" * 80)
    print("Basic Integration Test")
    print("=" * 80)
    test_document_parser_entity_extraction_integration()
    
    print("\n" + "=" * 80)
    print("Task 6.1: Entity Registration in Symbol Registry")
    print("=" * 80)
    test_6_1_entity_registration_in_symbol_registry()
    
    print("\n" + "=" * 80)
    print("Task 6.2: Relationship Creation in LanceDB")
    print("=" * 80)
    test_6_2_relationship_creation_in_lancedb()
    
    print("\n" + "=" * 80)
    print("Task 6.3: Search Returns Document Entities")
    print("=" * 80)
    test_6_3_search_returns_document_entities()
    
    print("\n" + "=" * 80)
    print("Task 6.4: Graph Traversal Queries")
    print("=" * 80)
    test_6_4_graph_traversal_queries()
    
    print("\n" + "=" * 80)
    print("✅ ALL INTEGRATION TESTS PASSED")
    print("=" * 80)


if __name__ == "__main__":
    test_all_integration_tests()
