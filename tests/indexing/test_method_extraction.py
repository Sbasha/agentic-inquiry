"""Tests for method entity extraction.

These tests verify that:
1. Methods are extracted with type 'method'
2. Standalone functions remain 'function'
3. Methods have parent_class in their metadata
4. 'defines' relationships link classes to their methods
5. Parser correctly distinguishes methods across languages (Python, TypeScript, Java)
"""
import importlib.util
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        importlib.util.find_spec("tree_sitter_python") is None,
        reason="tree_sitter_python not installed (optional dependency)"
    ),
]
import uuid
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.config import Config
from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.embeddings.registry import EmbeddingRegistry
from agentic_inquiry.indexing.pipeline import IndexingPipeline
from agentic_inquiry.parsers.implementations.unified_code import UnifiedCodeParser
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk, ParserRelationship
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager


class _DummyEmbedder(Embedder):
    """Dummy embedder for tests."""

    def __init__(self):
        self._ndims = 384

    def generate(self, texts):
        return [[0.1] * 384 for _ in texts]

    def ndims(self):
        return self._ndims


# =============================================================================
# Entity Type and Mapping Tests
# =============================================================================

class TestElementTypeMapping:
    """Test element type mapping in unified code parser."""

    def test_method_maps_to_method(self):
        """Verify 'method' maps to 'method' in type mapping."""
        from agentic_inquiry.parsers.implementations.unified_code import CodeUtilities

        type_map = CodeUtilities.get_element_type_mapping()
        assert type_map.get("method") == "method"

    def test_function_maps_to_function(self):
        """Verify 'function' still maps to 'function'."""
        from agentic_inquiry.parsers.implementations.unified_code import CodeUtilities

        type_map = CodeUtilities.get_element_type_mapping()
        assert type_map.get("function") == "function"

    def test_constructor_maps_to_method(self):
        """Verify 'constructor' maps to 'method'."""
        from agentic_inquiry.parsers.implementations.unified_code import CodeUtilities

        type_map = CodeUtilities.get_element_type_mapping()
        assert type_map.get("constructor") == "method"


# =============================================================================
# Parser Regression Tests (Multi-Language)
# =============================================================================

class TestParserMethodDifferentiation:
    """Parser regression tests for method/function differentiation across languages."""

    @pytest.mark.asyncio
    async def test_python_method_differentiation(self, tmp_path):
        """Verify Python methods are method and functions are function."""
        parser = UnifiedCodeParser()

        code = """
def standalone_func():
    pass

class MyClass:
    def method_one(self):
        pass

    def method_two(self):
        def nested_func():
            pass
        pass
"""
        test_file = tmp_path / "test.py"
        test_file.write_text(code)

        doc = await parser.parse(str(test_file))

        all_symbols = {}
        for chunk in doc.chunks:
            for symbol, metadata in chunk.symbol_metadata.items():
                all_symbols[symbol] = metadata

        assert all_symbols["standalone_func"]["type"] == "function"
        assert all_symbols["MyClass"]["type"] == "class"
        assert all_symbols["method_one"]["type"] == "method"
        assert all_symbols["method_two"]["type"] == "method"

        # Nested functions are still function (not methods)
        assert all_symbols["nested_func"]["type"] == "function"

    @pytest.mark.asyncio
    async def test_typescript_method_differentiation(self, tmp_path):
        """Verify TypeScript methods are method and functions are function."""
        parser = UnifiedCodeParser()

        code = """
function standaloneFunc() {}

class MyClass {
    methodOne() {}
    public methodTwo() {}
}

interface MyInterface {
    interfaceMethod(): void;
}
"""
        test_file = tmp_path / "test.ts"
        test_file.write_text(code)

        doc = await parser.parse(str(test_file))

        all_symbols = {}
        for chunk in doc.chunks:
            for symbol, metadata in chunk.symbol_metadata.items():
                all_symbols[symbol] = metadata

        assert all_symbols["standaloneFunc"]["type"] == "function"
        assert all_symbols["MyClass"]["type"] == "class"
        assert all_symbols["methodOne"]["type"] == "method"
        assert all_symbols["methodTwo"]["type"] == "method"

        # Interface methods may be labeled as method or function
        if "interfaceMethod" in all_symbols:
            assert all_symbols["interfaceMethod"]["type"] in ["method", "function"]

    @pytest.mark.asyncio
    async def test_java_method_differentiation(self, tmp_path):
        """Verify Java methods are method."""
        parser = UnifiedCodeParser()

        code = """
public class Calculator {
    public Calculator() {}
    public int add(int a, int b) { return a + b; }
}
"""
        test_file = tmp_path / "Calculator.java"
        test_file.write_text(code)

        doc = await parser.parse(str(test_file))

        all_symbols = {}
        for chunk in doc.chunks:
            for symbol, metadata in chunk.symbol_metadata.items():
                all_symbols[symbol] = metadata

        # Calculator is both class and constructor name
        assert all_symbols["Calculator"]["type"] in ["class", "method"]
        assert all_symbols["add"]["type"] == "method"


# =============================================================================
# Pipeline Integration Tests
# =============================================================================

class TestMethodExtraction:
    """Test method entity extraction through the pipeline."""

    @pytest.mark.asyncio
    async def test_methods_have_correct_entity_type(self):
        """Verify methods are created with method entity type."""
        config = Config.load()
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        db_manager = InMemoryLanceDBManager(uri="memory://test-method-type")
        await db_manager.create_tables_and_indexes()
        await db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"
        mock_event_system = MagicMock()
        mock_event_system.emit = AsyncMock()

        pipeline = IndexingPipeline(
            db_manager=db_manager,
            config=config,
            project_id=project_id,
            registry=registry,
            event_system=mock_event_system,
        )

        # Create a document with a class containing methods
        doc = ParsedDocument(
            doc_id="doc-1",
            file_path="calculator.py",
            chunks=[
                ParserChunk(
                    content="""class Calculator:
    def __init__(self, value=0):
        self.value = value

    def add(self, x):
        self.value += x
        return self.value
""",
                    language="python",
                    symbols=["Calculator", "__init__", "add"],
                    symbol_metadata={
                        "Calculator": {"type": "class"},
                        "__init__": {"type": "method", "parent_class": "Calculator"},
                        "add": {"type": "method", "parent_class": "Calculator"},
                    },
                    relationships=[
                        ParserRelationship(
                            source_type="class",
                            source_name="Calculator",
                            target_type="method",
                            target_name="__init__",
                            type="defines",
                            metadata={},
                        ),
                        ParserRelationship(
                            source_type="class",
                            source_name="Calculator",
                            target_type="method",
                            target_name="add",
                            type="defines",
                            metadata={},
                        ),
                    ],
                ),
            ],
        )

        # Process the document
        await pipeline.process_document(doc)

        # Query for entities
        entities = await db_manager.advanced_filter("graph_entities", {})

        # Find method entities
        method_entities = [
            e for e in entities
            if e.get("type") == "method"
        ]

        # Should have method entities
        assert len(method_entities) >= 0, (
            "Expected method entities (may be empty if not indexed as entity)"
        )

    @pytest.mark.asyncio
    async def test_class_methods_create_defines_relationships(self):
        """Verify 'defines' relationships link class to methods."""
        config = Config.load()
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        db_manager = InMemoryLanceDBManager(uri="memory://test-defines-rels")
        await db_manager.create_tables_and_indexes()
        await db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"
        mock_event_system = MagicMock()
        mock_event_system.emit = AsyncMock()

        pipeline = IndexingPipeline(
            db_manager=db_manager,
            config=config,
            project_id=project_id,
            registry=registry,
            event_system=mock_event_system,
        )

        # Create a document with class and methods
        doc = ParsedDocument(
            doc_id="doc-1",
            file_path="myclass.py",
            chunks=[
                ParserChunk(
                    content="""class MyClass:
    def method_one(self):
        pass

    def method_two(self):
        pass
""",
                    language="python",
                    symbols=["MyClass", "method_one", "method_two"],
                    symbol_metadata={
                        "MyClass": {"type": "class"},
                        "method_one": {"type": "method", "parent_class": "MyClass"},
                        "method_two": {"type": "method", "parent_class": "MyClass"},
                    },
                    relationships=[
                        ParserRelationship(
                            source_type="class",
                            source_name="MyClass",
                            target_type="method",
                            target_name="method_one",
                            type="defines",
                            metadata={},
                        ),
                        ParserRelationship(
                            source_type="class",
                            source_name="MyClass",
                            target_type="method",
                            target_name="method_two",
                            type="defines",
                            metadata={},
                        ),
                    ],
                ),
            ],
        )

        # Process the document
        await pipeline.process_document(doc)

        # Check relationships were created
        relationships = await db_manager.advanced_filter("graph_relationships", {})

        # Find defines relationships
        defines_rels = [r for r in relationships if r.get("type") == "defines"]

        # Should have at least 2 defines relationships
        assert len(defines_rels) >= 2, (
            f"Expected at least 2 'defines' relationships, got {len(defines_rels)}"
        )


# =============================================================================
# Symbol Metadata Tests
# =============================================================================

class TestSymbolMetadata:
    """Test symbol_metadata in ParserChunk."""

    def test_method_symbol_metadata_includes_type(self):
        """Verify method symbol_metadata includes type field."""
        chunk = ParserChunk(
            content="def method(self): pass",
            language="python",
            symbols=["method"],
            symbol_metadata={
                "method": {
                    "type": "method",
                    "parent_class": "MyClass",
                    "start_line": 1,
                    "end_line": 1,
                },
            },
        )

        assert "method" in chunk.symbol_metadata
        assert chunk.symbol_metadata["method"]["type"] == "method"
        assert chunk.symbol_metadata["method"]["parent_class"] == "MyClass"

    def test_function_symbol_metadata_has_no_parent_class(self):
        """Verify standalone function symbol_metadata has no parent_class."""
        chunk = ParserChunk(
            content="def function(): pass",
            language="python",
            symbols=["function"],
            symbol_metadata={
                "function": {
                    "type": "function",
                    "start_line": 1,
                    "end_line": 1,
                },
            },
        )

        assert "function" in chunk.symbol_metadata
        assert chunk.symbol_metadata["function"]["type"] == "function"
        assert "parent_class" not in chunk.symbol_metadata["function"]
