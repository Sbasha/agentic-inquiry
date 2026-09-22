"""Test SymbolRegistry encapsulation and public API.

This test suite verifies that:
1. All public API methods work correctly
2. Private attributes (_module_paths, _by_file) are not accessed externally
3. The public API provides sufficient functionality without direct attribute access

Requirements: 6.1, 6.2, 6.3
"""

import pytest

pytestmark = pytest.mark.unit
from agent_vault.indexing.symbol_registry import SymbolRegistry


class TestSymbolRegistryPublicAPI:
    """Test that public API methods provide all necessary functionality."""

    @pytest.fixture
    def registry(self, tmp_path):
        """Create a symbol registry for testing."""
        return SymbolRegistry(
            project_root=str(tmp_path),
            project_id="test_project"
        )

    @pytest.mark.asyncio
    async def test_register_and_lookup_by_name(self, registry):
        """Test registering and looking up symbols by name."""
        # Register a symbol
        await registry.register(
            name="MyClass",
            file_path="src/module.py",
            entity_type="class",
            language="python",
            line_start=10,
            line_end=50
        )

        # Lookup by name
        results = registry.lookup_by_name("MyClass")
        assert len(results) == 1
        assert results[0].name == "MyClass"
        assert results[0].file_path == "src/module.py"
        assert results[0].entity_type == "class"

    @pytest.mark.asyncio
    async def test_register_and_lookup_by_name_and_type(self, registry):
        """Test registering and looking up symbols by name and type."""
        # Register multiple symbols with same name but different types
        await registry.register(
            name="process",
            file_path="src/module.py",
            entity_type="function",
            language="python"
        )
        await registry.register(
            name="process",
            file_path="src/other.py",
            entity_type="class",
            language="python"
        )

        # Lookup by name and type (using the exact type names that were registered)
        functions = registry.lookup_by_name_and_type("process", "function")
        classes = registry.lookup_by_name_and_type("process", "class")

        assert len(functions) == 1
        assert functions[0].entity_type == "function"
        assert len(classes) == 1
        assert classes[0].entity_type == "class"

    @pytest.mark.asyncio
    async def test_lookup_protocol_method(self, registry):
        """Test the async lookup method (protocol-compatible)."""
        await registry.register(
            name="MyClass",
            file_path="src/module.py",
            entity_type="class",
            language="python"
        )

        # Lookup without type hint
        results = await registry.lookup("MyClass")
        assert len(results) == 1

        # Lookup with type hint
        results = await registry.lookup("MyClass", type_hint="class")
        assert len(results) == 1
        assert results[0].entity_type == "class"

    @pytest.mark.asyncio
    async def test_get_symbol_count(self, registry):
        """Test getting symbol count through public API."""
        # Initially empty
        assert registry.get_symbol_count() == 0

        # Register symbols
        await registry.register(
            name="ClassA",
            file_path="src/a.py",
            entity_type="class",
            language="python"
        )
        await registry.register(
            name="ClassB",
            file_path="src/b.py",
            entity_type="class",
            language="python"
        )

        # Check count
        assert registry.get_symbol_count() == 2

    @pytest.mark.asyncio
    async def test_get_file_count(self, registry):
        """Test getting file count through public API."""
        # Initially empty
        assert registry.get_file_count() == 0

        # Register symbols from different files
        await registry.register(
            name="ClassA",
            file_path="src/a.py",
            entity_type="class",
            language="python"
        )
        await registry.register(
            name="ClassB",
            file_path="src/a.py",
            entity_type="class",
            language="python"
        )
        await registry.register(
            name="ClassC",
            file_path="src/b.py",
            entity_type="class",
            language="python"
        )

        # Check file count (2 unique files)
        assert registry.get_file_count() == 2

    @pytest.mark.asyncio
    async def test_get_statistics(self, registry):
        """Test getting comprehensive statistics through public API."""
        # Register various symbols
        await registry.register(
            name="ClassA",
            file_path="src/a.py",
            entity_type="class",
            language="python"
        )
        await registry.register(
            name="func_a",
            file_path="src/a.py",
            entity_type="function",
            language="python"
        )
        await registry.register(
            name="ClassB",
            file_path="src/b.py",
            entity_type="class",
            language="python"
        )

        # Track some imports
        await registry.track_import("ClassA", "src/main.py", "src/a.py")
        await registry.track_import("ClassA", "src/other.py", "src/a.py")

        # Get statistics
        stats = registry.get_statistics()

        assert stats["symbol_count"] == 3
        assert stats["file_count"] == 2
        assert "class" in stats["type_breakdown"]
        assert stats["type_breakdown"]["class"] == 2
        assert "function" in stats["type_breakdown"]
        assert stats["type_breakdown"]["function"] == 1
        assert len(stats["most_imported"]) > 0
        assert stats["most_imported"][0][0] == "ClassA"
        assert stats["most_imported"][0][1] == 2

    @pytest.mark.asyncio
    async def test_get_stats_protocol_method(self, registry):
        """Test the async get_stats method (protocol-compatible)."""
        await registry.register(
            name="ClassA",
            file_path="src/a.py",
            entity_type="class",
            language="python"
        )

        stats = await registry.get_stats()

        assert "total_symbols" in stats
        assert "total_files" in stats
        assert "module_paths" in stats
        assert stats["total_symbols"] == 1
        assert stats["total_files"] == 1

    @pytest.mark.asyncio
    async def test_remove_file_symbols(self, registry):
        """Test removing symbols from a file through public API."""
        # Register symbols
        await registry.register(
            name="ClassA",
            file_path="src/a.py",
            entity_type="class",
            language="python"
        )
        await registry.register(
            name="ClassB",
            file_path="src/b.py",
            entity_type="class",
            language="python"
        )

        assert registry.get_symbol_count() == 2
        assert registry.get_file_count() == 2

        # Remove symbols from one file
        registry.remove_file_symbols("src/a.py")

        assert registry.get_symbol_count() == 1
        assert registry.get_file_count() == 1

        # Verify the correct symbol was removed
        results = registry.lookup_by_name("ClassA")
        assert len(results) == 0
        results = registry.lookup_by_name("ClassB")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_clear_all_symbols(self, registry):
        """Test clearing all symbols through public API."""
        # Register symbols
        await registry.register(
            name="ClassA",
            file_path="src/a.py",
            entity_type="class",
            language="python"
        )
        await registry.register(
            name="ClassB",
            file_path="src/b.py",
            entity_type="class",
            language="python"
        )

        assert registry.get_symbol_count() == 2

        # Clear all
        await registry.clear()

        assert registry.get_symbol_count() == 0
        assert registry.get_file_count() == 0

    @pytest.mark.asyncio
    async def test_track_import_and_get_frequency(self, registry):
        """Test tracking imports and getting frequency through public API."""
        await registry.register(
            name="MyClass",
            file_path="src/module.py",
            entity_type="class",
            language="python"
        )

        # Initially no imports
        assert registry.get_import_frequency("MyClass") == 0

        # Track imports
        await registry.track_import("MyClass", "src/main.py", "src/module.py")
        await registry.track_import("MyClass", "src/other.py", "src/module.py")
        await registry.track_import("MyClass", "src/third.py", "src/module.py")

        # Check frequency
        assert registry.get_import_frequency("MyClass") == 3

    @pytest.mark.asyncio
    async def test_get_co_occurrence_score(self, registry):
        """Test getting co-occurrence scores through public API."""
        await registry.register(
            name="MyClass",
            file_path="src/module.py",
            entity_type="class",
            language="python"
        )

        # Initially no co-occurrence
        assert registry.get_co_occurrence_score("src/main.py", "src/module.py") == 0

        # Track imports
        await registry.track_import("MyClass", "src/main.py", "src/module.py")
        await registry.track_import("MyClass", "src/main.py", "src/module.py")

        # Check co-occurrence
        assert registry.get_co_occurrence_score("src/main.py", "src/module.py") == 2

    @pytest.mark.asyncio
    async def test_resolve_with_cache(self, registry):
        """Test symbol resolution through public API."""
        # Register symbols
        await registry.register(
            name="MyClass",
            file_path="src/module.py",
            entity_type="class",
            language="python"
        )

        # Resolve symbol
        result = registry.resolve_with_cache("MyClass", "class", "src/main.py")

        assert result is not None
        file_path, entity_type, confidence = result
        assert file_path == "src/module.py"
        assert entity_type == "class"
        assert confidence > 0

    @pytest.mark.asyncio
    async def test_cache_operations(self, registry):
        """Test cache operations through public API."""
        await registry.register(
            name="MyClass",
            file_path="src/module.py",
            entity_type="class",
            language="python"
        )

        # First resolution (cache miss)
        registry.resolve_with_cache("MyClass", "class", "src/main.py")

        # Get cache info
        cache_info = registry.get_cache_info()
        assert "hits" in cache_info
        assert "misses" in cache_info
        assert "size" in cache_info
        assert cache_info["misses"] >= 1

        # Second resolution (cache hit)
        registry.resolve_with_cache("MyClass", "class", "src/main.py")
        cache_info = registry.get_cache_info()
        assert cache_info["hits"] >= 1

        # Clear cache
        registry.clear_cache()
        cache_info = registry.get_cache_info()
        assert cache_info["size"] == 0


class TestSymbolRegistryEncapsulation:
    """Test that private attributes are properly encapsulated."""

    def test_private_attributes_not_in_public_api(self):
        """Verify that private attributes are not part of the public API."""
        registry = SymbolRegistry(project_root=".", project_id="test")

        # These attributes should exist (they're private)
        assert hasattr(registry, "_module_paths")
        assert hasattr(registry, "_by_file")
        assert hasattr(registry, "_by_name")
        assert hasattr(registry, "_by_name_type")

        # But they should be prefixed with underscore (convention for private)
        assert not hasattr(registry, "module_paths")
        assert not hasattr(registry, "by_file")

    def test_public_methods_provide_sufficient_functionality(self):
        """Verify that public methods provide all necessary functionality.
        
        This test documents that external code should use public methods
        instead of accessing private attributes directly.
        """
        registry = SymbolRegistry(project_root=".", project_id="test")

        # Public methods that should be used instead of private attribute access:
        
        # Instead of accessing _by_file, use:
        assert callable(registry.get_file_count)
        assert callable(registry.remove_file_symbols)
        assert callable(registry.get_statistics)
        
        # Instead of accessing _module_paths, use:
        assert callable(registry.lookup_by_name)
        assert callable(registry.lookup_by_name_and_type)
        assert callable(registry.resolve_with_cache)
        
        # Instead of accessing _by_name, use:
        assert callable(registry.lookup_by_name)
        assert callable(registry.get_symbol_count)
        
        # General statistics and info:
        assert callable(registry.get_stats)
        assert callable(registry.get_statistics)

    @pytest.mark.asyncio
    async def test_external_code_pattern_file_symbols(self):
        """Test the correct pattern for checking if a file has symbols.
        
        This demonstrates the correct way to check if a file has registered symbols
        without accessing _by_file directly.
        """
        registry = SymbolRegistry(project_root=".", project_id="test")

        # Register a symbol
        await registry.register(
            name="MyClass",
            file_path="src/module.py",
            entity_type="class",
            language="python"
        )

        # CORRECT: Use get_statistics to check file count
        stats = registry.get_statistics()
        assert stats["file_count"] > 0

        # CORRECT: Use get_file_count
        assert registry.get_file_count() > 0

        # CORRECT: Try to remove and check if it existed
        # (remove_file_symbols is idempotent and logs if file not found)
        registry.remove_file_symbols("src/module.py")
        assert registry.get_file_count() == 0

    @pytest.mark.asyncio
    async def test_external_code_pattern_module_lookup(self):
        """Test the correct pattern for looking up symbols by module path.
        
        This demonstrates the correct way to resolve symbols without accessing
        _module_paths directly.
        """
        registry = SymbolRegistry(project_root=".", project_id="test")

        # Register a symbol
        await registry.register(
            name="MyClass",
            file_path="src/module.py",
            entity_type="class",
            language="python"
        )

        # CORRECT: Use resolve_with_cache for resolution
        result = registry.resolve_with_cache("MyClass", "class", "src/main.py")
        assert result is not None

        # CORRECT: Use lookup_by_name or lookup_by_name_and_type
        results = registry.lookup_by_name("MyClass")
        assert len(results) > 0

        # CORRECT: Use the async lookup method
        results = await registry.lookup("MyClass")
        assert len(results) > 0


class TestSymbolRegistryIntegration:
    """Integration tests showing proper usage patterns."""

    @pytest.mark.asyncio
    async def test_complete_workflow_without_private_access(self):
        """Test a complete workflow using only public API methods."""
        registry = SymbolRegistry(project_root=".", project_id="test")

        # 1. Register symbols
        await registry.register(
            name="ClassA",
            file_path="src/a.py",
            entity_type="class",
            language="python"
        )
        await registry.register(
            name="ClassB",
            file_path="src/b.py",
            entity_type="class",
            language="python"
        )
        await registry.register(
            name="func_a",
            file_path="src/a.py",
            entity_type="function",
            language="python"
        )

        # 2. Query statistics
        assert registry.get_symbol_count() == 3
        assert registry.get_file_count() == 2

        # 3. Lookup symbols
        classes = registry.lookup_by_name_and_type("ClassA", "class")
        assert len(classes) == 1

        # 4. Track imports
        await registry.track_import("ClassA", "src/main.py", "src/a.py")
        assert registry.get_import_frequency("ClassA") == 1

        # 5. Resolve symbols
        result = registry.resolve_with_cache("ClassA", "class", "src/main.py")
        assert result is not None

        # 6. Get comprehensive statistics
        stats = registry.get_statistics()
        assert stats["symbol_count"] == 3
        assert stats["file_count"] == 2

        # 7. Remove file symbols
        registry.remove_file_symbols("src/a.py")
        assert registry.get_symbol_count() == 1
        assert registry.get_file_count() == 1

        # 8. Clear all
        await registry.clear()
        assert registry.get_symbol_count() == 0
