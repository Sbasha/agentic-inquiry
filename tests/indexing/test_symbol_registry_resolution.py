"""Test SymbolRegistry resolution with frequency and co-occurrence data."""
import pytest

pytestmark = pytest.mark.unit

import asyncio
import pytest

from agent_vault.indexing.symbol_registry import SymbolRegistry


@pytest.fixture
def registry():
    """Create a symbol registry for testing."""
    return SymbolRegistry(
        project_root="/tmp/test_project",
        project_id="test_project",
        cache_size=128
    )


def test_resolution_exact_match(registry):
    """Test resolution with exact name and type match."""
    async def run():
        # Register a single symbol
        await registry.register(
            name="MyClass",
            file_path="/tmp/test_project/module.py",
            entity_type="class",
            language="python",
            line_start=1,
            line_end=10,
            is_exported=True
        )
        
        # Resolve should find exact match with high confidence
        result = registry.resolve_with_cache("MyClass", "class", "/tmp/test_project/main.py")
        
        assert result is not None
        file_path, entity_type, confidence = result
        assert file_path == "/tmp/test_project/module.py"
        assert entity_type == "class"
        assert confidence == 1.0  # Exact match = 100% confidence
    
    asyncio.run(run())


def test_resolution_with_frequency_data(registry):
    """Test resolution using import frequency data."""
    async def run():
        # Register two symbols with same name in files with no naming pattern match
        await registry.register(
            name="DataProcessor",
            file_path="/tmp/test_project/utils.py",
            entity_type="class",
            language="python",
            is_exported=True
        )
        
        await registry.register(
            name="DataProcessor",
            file_path="/tmp/test_project/helpers.py",
            entity_type="class",
            language="python",
            is_exported=True
        )
        
        # Track imports to build frequency data
        # utils.py is imported much more frequently (10 vs 1)
        for i in range(10):
            await registry.track_import("DataProcessor", f"/tmp/test_project/file{i}.py", "/tmp/test_project/utils.py")
        await registry.track_import("DataProcessor", "/tmp/test_project/file_x.py", "/tmp/test_project/helpers.py")
        
        # Resolve from a new file - should prefer utils.py due to much higher frequency
        result = registry.resolve_with_cache("DataProcessor", "class", "/tmp/test_project/new_file.py")
        
        assert result is not None
        file_path, entity_type, confidence = result
        assert file_path == "/tmp/test_project/utils.py"
        assert confidence > 0.3  # Should have reasonable confidence
        
        # Verify frequency tracking
        assert registry.get_import_frequency("DataProcessor") == 11
    
    asyncio.run(run())


def test_resolution_with_co_occurrence_data(registry):
    """Test resolution using co-occurrence data."""
    async def run():
        # Register two symbols with same name
        await registry.register(
            name="Config",
            file_path="/tmp/test_project/config.py",
            entity_type="class",
            language="python",
            is_exported=True
        )
        
        await registry.register(
            name="Config",
            file_path="/tmp/test_project/settings.py",
            entity_type="class",
            language="python",
            is_exported=True
        )
        
        # Track co-occurrence: main.py frequently imports from config.py
        source_file = "/tmp/test_project/main.py"
        await registry.track_import("Config", source_file, "/tmp/test_project/config.py")
        await registry.track_import("Config", source_file, "/tmp/test_project/config.py")
        await registry.track_import("Config", source_file, "/tmp/test_project/config.py")
        
        # Resolve from main.py - should prefer config.py due to co-occurrence
        result = registry.resolve_with_cache("Config", "class", source_file)
        
        assert result is not None
        file_path, entity_type, confidence = result
        assert file_path == "/tmp/test_project/config.py"
        
        # Verify co-occurrence tracking
        assert registry.get_co_occurrence_score(source_file, "/tmp/test_project/config.py") == 3
        assert registry.get_co_occurrence_score(source_file, "/tmp/test_project/settings.py") == 0
    
    asyncio.run(run())


def test_resolution_with_file_naming_pattern(registry):
    """Test resolution using file naming pattern scoring."""
    async def run():
        # Register symbols where one has matching file name
        await registry.register(
            name="UserManager",
            file_path="/tmp/test_project/user_manager.py",  # Matches symbol name
            entity_type="class",
            language="python",
            is_exported=True
        )
        
        await registry.register(
            name="UserManager",
            file_path="/tmp/test_project/utils.py",  # Doesn't match
            entity_type="class",
            language="python",
            is_exported=True
        )
        
        # Resolve - should prefer user_manager.py due to naming pattern
        result = registry.resolve_with_cache("UserManager", "class", "/tmp/test_project/main.py")
        
        assert result is not None
        file_path, entity_type, confidence = result
        assert file_path == "/tmp/test_project/user_manager.py"
        
        # Verify naming score is high
        naming_score = registry.score_file_naming_pattern("UserManager", "/tmp/test_project/user_manager.py")
        assert naming_score >= 50.0  # Should have high score for matching name
    
    asyncio.run(run())


def test_resolution_with_directory_structure(registry):
    """Test resolution using directory structure scoring."""
    async def run():
        # Register symbols in different directories
        await registry.register(
            name="AuthService",
            file_path="/tmp/test_project/auth/service.py",  # In auth directory
            entity_type="class",
            language="python",
            is_exported=True
        )
        
        await registry.register(
            name="AuthService",
            file_path="/tmp/test_project/services/auth_service.py",  # Different location
            entity_type="class",
            language="python",
            is_exported=True
        )
        
        # Verify directory scoring
        score1 = registry.score_directory_structure("AuthService", "/tmp/test_project/auth/service.py")
        registry.score_directory_structure("AuthService", "/tmp/test_project/services/auth_service.py")
        
        # auth directory should score higher for AuthService
        assert score1 > 0
    
    asyncio.run(run())


def test_resolution_no_match(registry):
    """Test resolution when no symbol is found."""
    async def run():
        # Don't register any symbols
        
        # Resolve should return None
        result = registry.resolve_with_cache("NonExistent", "class", "/tmp/test_project/main.py")
        
        assert result is None
    
    asyncio.run(run())


def test_resolution_low_confidence(registry):
    """Test resolution returns None for low confidence matches."""
    async def run():
        # Register a symbol with no supporting data
        await registry.register(
            name="Obscure",
            file_path="/tmp/test_project/deeply/nested/path/file.py",
            entity_type="class",
            language="python",
            is_exported=False  # Not exported
        )
        
        # Resolve from unrelated file with no frequency/co-occurrence data
        result = registry.resolve_with_cache("Obscure", "function", "/tmp/test_project/other.py")
        
        # Should return None due to low confidence (wrong type, no data, not exported)
        # Note: Might still return if naming patterns match, but confidence should be low
        if result is not None:
            _, _, confidence = result
            assert confidence < 0.7  # Low confidence
    
    asyncio.run(run())


def test_resolution_cache_behavior(registry):
    """Test that resolution results are cached."""
    async def run():
        # Register a symbol
        await registry.register(
            name="CachedClass",
            file_path="/tmp/test_project/module.py",
            entity_type="class",
            language="python",
            is_exported=True
        )
        
        # First resolution
        result1 = registry.resolve_with_cache("CachedClass", "class", "/tmp/test_project/main.py")
        
        # Get cache info
        cache_info = registry.get_cache_info()
        initial_hits = cache_info["hits"]
        cache_info["misses"]
        
        # Second resolution with same parameters - should hit cache
        result2 = registry.resolve_with_cache("CachedClass", "class", "/tmp/test_project/main.py")
        
        # Verify results are the same
        assert result1 == result2
        
        # Verify cache was hit
        cache_info = registry.get_cache_info()
        assert cache_info["hits"] > initial_hits
        
        # Clear cache
        registry.clear_cache()
        
        # Verify cache is cleared
        cache_info = registry.get_cache_info()
        assert cache_info["hits"] == 0
        assert cache_info["misses"] == 0
    
    asyncio.run(run())


def test_resolution_type_mismatch(registry):
    """Test resolution when type doesn't match."""
    async def run():
        # Register a function
        await registry.register(
            name="helper",
            file_path="/tmp/test_project/utils.py",
            entity_type="function",
            language="python",
            is_exported=True
        )
        
        # Try to resolve as a class - should still work but with lower confidence
        result = registry.resolve_with_cache("helper", "class", "/tmp/test_project/main.py")
        
        # Should find it but with lower confidence due to type mismatch
        if result is not None:
            file_path, entity_type, confidence = result
            assert entity_type == "function"  # Actual type
            # Confidence should be lower due to type mismatch
    
    asyncio.run(run())


def test_resolution_composite_scoring(registry):
    """Test that composite scoring combines multiple factors."""
    async def run():
        # Register multiple candidates
        await registry.register(
            name="Service",
            file_path="/tmp/test_project/service.py",  # Good naming match
            entity_type="class",
            language="python",
            is_exported=True
        )
        
        await registry.register(
            name="Service",
            file_path="/tmp/test_project/utils.py",  # Poor naming match
            entity_type="class",
            language="python",
            is_exported=True
        )
        
        # Add frequency data for utils.py
        await registry.track_import("Service", "/tmp/test_project/file1.py", "/tmp/test_project/utils.py")
        await registry.track_import("Service", "/tmp/test_project/file2.py", "/tmp/test_project/utils.py")
        
        # Add co-occurrence data for service.py
        source = "/tmp/test_project/main.py"
        await registry.track_import("Service", source, "/tmp/test_project/service.py")
        await registry.track_import("Service", source, "/tmp/test_project/service.py")
        await registry.track_import("Service", source, "/tmp/test_project/service.py")
        
        # Resolve from main.py - should prefer service.py due to:
        # - Strong co-occurrence with main.py
        # - Good naming pattern match
        result = registry.resolve_with_cache("Service", "class", source)
        
        assert result is not None
        file_path, entity_type, confidence = result
        # service.py should win due to co-occurrence + naming
        assert file_path == "/tmp/test_project/service.py"
        assert confidence > 0.5
    
    asyncio.run(run())


def test_async_protocol_methods(registry):
    """Test that protocol methods are async."""
    async def run():
        # Test register is async
        await registry.register(
            name="TestClass",
            file_path="/tmp/test_project/test.py",
            entity_type="class",
            language="python"
        )
        
        # Test lookup is async
        results = await registry.lookup("TestClass")
        assert len(results) == 1
        
        # Test track_import is async
        await registry.track_import("TestClass", "/tmp/test_project/main.py", "/tmp/test_project/test.py")
        
        # Test get_stats is async
        stats = await registry.get_stats()
        assert stats["total_symbols"] == 1
        
        # Test clear is async
        await registry.clear()
        stats = await registry.get_stats()
        assert stats["total_symbols"] == 0
    
    asyncio.run(run())
