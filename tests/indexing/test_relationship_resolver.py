"""Tests for RelationshipResolver service.

Tests each resolution strategy and proximity scoring using real parser samples
with both in-file and cross-file relationships.
"""

import pytest

pytestmark = pytest.mark.integration

import tempfile
from pathlib import Path

from agent_vault.indexing.relationship_resolver import RelationshipResolver
from agent_vault.indexing.symbol_registry import SymbolRegistry
from agent_vault.parsers.executor import get_parser_instance


# Sample Python files with relationships
SAMPLE_MODULE_A = '''"""Module A with class definitions."""

class DataProcessor:
    """Process data."""
    
    def process(self, data):
        return data.upper()


class ConfigManager:
    """Manage configuration."""
    
    def load_config(self, path):
        return {"path": path}
'''

SAMPLE_MODULE_B = '''"""Module B that imports from Module A."""
from module_a import DataProcessor, ConfigManager


class ServiceLayer:
    """Service layer using DataProcessor."""
    
    def __init__(self):
        self.processor = DataProcessor()
        self.config = ConfigManager()
    
    def run(self, data):
        return self.processor.process(data)
'''

SAMPLE_MODULE_C = '''"""Module C with nested imports."""
from module_b import ServiceLayer
from module_a import ConfigManager


def main():
    """Main entry point."""
    service = ServiceLayer()
    config = ConfigManager()
    result = service.run("test")
    return result
'''


@pytest.fixture
def temp_project():
    """Create a temporary project directory with sample files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        
        # Create sample files
        module_a = project_root / "module_a.py"
        module_a.write_text(SAMPLE_MODULE_A)
        
        module_b = project_root / "module_b.py"
        module_b.write_text(SAMPLE_MODULE_B)
        
        module_c = project_root / "module_c.py"
        module_c.write_text(SAMPLE_MODULE_C)
        
        yield project_root


@pytest.fixture
async def symbol_registry(temp_project):
    """Create and populate a symbol registry with sample files."""
    registry = SymbolRegistry(
        project_root=str(temp_project),
        project_id="test_project",
    )
    
    # Parse and register symbols from all files
    parser = get_parser_instance("unified_code")
    
    for file_path in temp_project.glob("*.py"):
        parsed_doc = await parser.parse(str(file_path))
        
        # Track which symbols we've already registered to avoid duplicates
        registered_symbols = set()
        
        # Register symbols from each chunk
        for chunk in parsed_doc.chunks:
            if chunk.symbols and chunk.symbol_metadata:
                for symbol_name in chunk.symbols:
                    # Skip if already registered
                    symbol_key = (symbol_name, str(file_path))
                    if symbol_key in registered_symbols:
                        continue
                    
                    metadata = chunk.symbol_metadata.get(symbol_name, {})
                    await registry.register(
                        name=symbol_name,
                        file_path=str(file_path),
                        entity_type=metadata.get("type", "unknown"),
                        language=chunk.language,
                        line_start=metadata.get("start_line", chunk.line_start),
                        line_end=metadata.get("end_line", chunk.line_end),
                        is_exported=True,  # Assume exported for test purposes
                    )
                    registered_symbols.add(symbol_key)
    
    return registry


@pytest.fixture
async def resolver(symbol_registry, temp_project):
    """Create a RelationshipResolver instance."""
    return RelationshipResolver(
        symbol_registry=symbol_registry,
        project_root=str(temp_project),
    )


class TestResolutionStrategies:
    """Test each resolution strategy."""
    
    @pytest.mark.asyncio
    async def test_exact_match_resolution(self, resolver, temp_project):
        """Test resolution by exact name and type match."""
        # DataProcessor is a class in module_a
        result = await resolver.resolve_import(
            target_name="DataProcessor",
            target_type="class",
            source_file=str(temp_project / "module_b.py"),
            source_language="python",
        )
        
        assert result is not None
        file_path, entity_type, confidence = result
        assert "module_a.py" in file_path
        assert entity_type == "class"
        assert confidence >= 0.9  # High confidence for exact match
    
    @pytest.mark.asyncio
    async def test_import_path_resolution(self, resolver, temp_project):
        """Test resolution using explicit import path."""
        result = await resolver.resolve_import(
            target_name="DataProcessor",
            target_type="class",
            source_file=str(temp_project / "module_b.py"),
            source_language="python",
            import_path="module_a",
        )
        
        assert result is not None
        file_path, entity_type, confidence = result
        assert "module_a.py" in file_path
        assert confidence == 1.0  # Perfect confidence with import path

    @pytest.mark.asyncio
    async def test_database_resolution(self, resolver, symbol_registry):
        """Test resolution using existing database relationships."""
        # Create a mock database manager
        from unittest.mock import AsyncMock
        
        mock_db = AsyncMock()
        resolver.db_manager = mock_db
        resolver._skip_database_lookups = False  # Enable database lookups for this test
        
        # Register symbols
        await symbol_registry.register(
            name="IndexingPipeline",
            file_path="agent_vault/indexing/pipeline.py",
            entity_type="class",
            language="python",
        )
        
        # Mock database response with existing relationship
        # Format: source_id = "{source_type}::{project_hash}::{source_file}::{source_name}"
        # Format: target_id = "{target_type}::{project_hash}::{target_file}::{target_name}"
        mock_db.query_raw.return_value = [
            {
                "id": "edge_12345678",
                "source_id": "module::test_project::agent_vault/search/service.py::SearchService",
                "target_id": "class::test_project::agent_vault/indexing/pipeline.py::IndexingPipeline",
                "type": "imports",
                "project_id": "test_project",
            }
        ]

        # Resolve using database
        result = await resolver.resolve_import(
            target_name="IndexingPipeline",
            target_type="class",
            source_file="agent_vault/search/service.py",
            source_language="python",
        )

        # Should resolve from database with confidence 1.0
        assert result is not None
        target_file, target_type, confidence = result
        assert target_file == "agent_vault/indexing/pipeline.py"
        assert target_type == "class"
        assert confidence == 1.0

        # Verify database was queried
        mock_db.query_raw.assert_called_once()
        call_args = mock_db.query_raw.call_args
        assert call_args[1]["table_name"] == "graph_relationships"
        assert call_args[1]["filters"]["relationship_type"] == "imports"

    @pytest.mark.asyncio
    async def test_database_resolution_no_match(self, resolver, symbol_registry):
        """Test database resolution when no matching relationship exists."""
        from unittest.mock import AsyncMock
        
        mock_db = AsyncMock()
        resolver.db_manager = mock_db
        resolver._skip_database_lookups = False  # Enable database lookups for this test
        
        # Register symbols for fallback resolution
        await symbol_registry.register(
            name="SomeClass",
            file_path="agent_vault/models/some_class.py",
            entity_type="class",
            language="python",
        )
        
        # Mock database response with no matching relationships
        mock_db.query_raw.return_value = []

        # Resolve - should fall back to other strategies
        result = await resolver.resolve_import(
            target_name="SomeClass",
            target_type="class",
            source_file="agent_vault/search/service.py",
            source_language="python",
        )

        # Should resolve using fallback strategy (exact match in this case)
        assert result is not None
        target_file, target_type, confidence = result
        assert target_file == "agent_vault/models/some_class.py"
        assert target_type == "class"
        # Confidence should be 1.0 for exact match fallback
        assert confidence == 1.0

        # Verify database was queried
        mock_db.query_raw.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_proximity_resolution(self, resolver, temp_project):
        """Test resolution by file proximity with perfect naming match."""
        # Create a file with perfect naming match for proximity resolution
        # File name matches class name exactly
        helper_file = temp_project / "user_manager.py"
        helper_file.write_text('''
class UserManager:
    """Manages users."""
    pass
''')
        
        # Register this symbol
        parser = get_parser_instance("unified_code")
        parsed_doc = await parser.parse(str(helper_file))
        for chunk in parsed_doc.chunks:
            if chunk.symbols and chunk.symbol_metadata:
                for symbol_name in chunk.symbols:
                    metadata = chunk.symbol_metadata.get(symbol_name, {})
                    await resolver.symbol_registry.register(
                        name=symbol_name,
                        file_path=str(helper_file),
                        entity_type=metadata.get("type", "unknown"),
                        language=chunk.language,
                        line_start=metadata.get("start_line", chunk.line_start),
                        line_end=metadata.get("end_line", chunk.line_end),
                        is_exported=True,
                    )
        
        # Now resolve without type hint - should use proximity + naming
        result = await resolver.resolve_import(
            target_name="UserManager",
            target_type=None,  # No type hint to force proximity
            source_file=str(temp_project / "module_b.py"),
            source_language="python",
        )
        
        # Should resolve due to perfect file naming match + proximity
        # Proximity: 0.8 (same dir) * 0.4 = 0.32
        # Naming: 100 (exact match) / 100 * 0.25 = 0.25
        # Total: 0.57 > 0.5 threshold
        assert result is not None, "Should resolve via proximity with perfect naming"
        file_path, entity_type, confidence = result
        assert "user_manager.py" in file_path
        assert confidence >= 0.5  # Should meet threshold with perfect naming match
    
    @pytest.mark.asyncio
    async def test_cross_file_resolution(self, resolver, temp_project):
        """Test resolving imports across multiple files."""
        # ServiceLayer is in module_b, imported by module_c
        result = await resolver.resolve_import(
            target_name="ServiceLayer",
            target_type="class",
            source_file=str(temp_project / "module_c.py"),
            source_language="python",
        )
        
        assert result is not None
        file_path, entity_type, confidence = result
        assert "module_b.py" in file_path
        assert entity_type == "class"
    
    @pytest.mark.asyncio
    async def test_unresolvable_import(self, resolver, temp_project):
        """Test that unresolvable imports return None."""
        result = await resolver.resolve_import(
            target_name="NonExistentClass",
            target_type="class",
            source_file=str(temp_project / "module_c.py"),
            source_language="python",
        )
        
        assert result is None


class TestProximityScoring:
    """Test proximity scoring calculations."""
    
    def test_same_directory_score(self, resolver, temp_project):
        """Test that files in same directory get high proximity score."""
        source = str(temp_project / "module_a.py")
        target = str(temp_project / "module_b.py")
        
        score = resolver._calculate_proximity_score(source, target)
        assert score == 0.8  # Same directory
    
    def test_different_directory_score(self, resolver, temp_project):
        """Test proximity score for files in different directories."""
        # Create subdirectory
        subdir = temp_project / "subdir"
        subdir.mkdir()
        sub_file = subdir / "module_d.py"
        sub_file.write_text("# test")
        
        source = str(temp_project / "module_a.py")
        target = str(sub_file)
        
        score = resolver._calculate_proximity_score(source, target)
        assert 0.3 <= score < 0.8  # Lower than same directory
    
    def test_same_file_score(self, resolver, temp_project):
        """Test that same file gets perfect score."""
        source = str(temp_project / "module_a.py")
        
        score = resolver._calculate_proximity_score(source, source)
        assert score == 1.0


class TestCaching:
    """Test resolution caching behavior."""
    
    @pytest.mark.asyncio
    async def test_cache_hit(self, resolver, temp_project):
        """Test that repeated resolutions use cache."""
        # First resolution
        result1 = await resolver.resolve_import(
            target_name="DataProcessor",
            target_type="class",
            source_file=str(temp_project / "module_b.py"),
            source_language="python",
        )
        
        # Second resolution (should hit cache)
        result2 = await resolver.resolve_import(
            target_name="DataProcessor",
            target_type="class",
            source_file=str(temp_project / "module_b.py"),
            source_language="python",
        )
        
        assert result1 == result2
        
        stats = resolver.get_resolution_stats()
        assert stats["cache_hits"] >= 1
        assert stats["total_attempts"] == 2
    
    @pytest.mark.asyncio
    async def test_cache_clear(self, resolver, temp_project):
        """Test clearing the resolution cache."""
        # Perform a resolution
        await resolver.resolve_import(
            target_name="DataProcessor",
            target_type="class",
            source_file=str(temp_project / "module_b.py"),
            source_language="python",
        )
        
        stats_before = resolver.get_resolution_stats()
        assert stats_before["cache_size"] > 0
        
        # Clear cache
        resolver.clear_cache()
        
        stats_after = resolver.get_resolution_stats()
        assert stats_after["cache_size"] == 0
    
    @pytest.mark.asyncio
    async def test_cache_hit_rate(self, resolver, temp_project):
        """Test cache hit rate calculation."""
        # First resolution (cache miss)
        await resolver.resolve_import(
            target_name="DataProcessor",
            target_type="class",
            source_file=str(temp_project / "module_b.py"),
            source_language="python",
        )
        
        # Cache hit rate should be 0% (0 hits, 1 miss)
        assert resolver.cache_hit_rate == 0.0
        
        # Second resolution (cache hit)
        await resolver.resolve_import(
            target_name="DataProcessor",
            target_type="class",
            source_file=str(temp_project / "module_b.py"),
            source_language="python",
        )
        
        # Cache hit rate should be 50% (1 hit, 1 miss)
        assert resolver.cache_hit_rate == 50.0
        
        # Third resolution (cache hit)
        await resolver.resolve_import(
            target_name="DataProcessor",
            target_type="class",
            source_file=str(temp_project / "module_b.py"),
            source_language="python",
        )
        
        # Cache hit rate should be 66.67% (2 hits, 1 miss)
        assert abs(resolver.cache_hit_rate - 66.67) < 0.1
        
        # Verify it's included in stats
        stats = resolver.get_resolution_stats()
        assert "cache_hit_rate" in stats
        assert stats["cache_hit_rate"] == resolver.cache_hit_rate


class TestStatistics:
    """Test resolution statistics tracking."""
    
    @pytest.mark.asyncio
    async def test_resolution_stats(self, resolver, temp_project):
        """Test that statistics are tracked correctly."""
        # Perform successful resolution
        await resolver.resolve_import(
            target_name="DataProcessor",
            target_type="class",
            source_file=str(temp_project / "module_b.py"),
            source_language="python",
        )
        
        # Perform failed resolution
        await resolver.resolve_import(
            target_name="NonExistent",
            target_type="class",
            source_file=str(temp_project / "module_b.py"),
            source_language="python",
        )
        
        stats = resolver.get_resolution_stats()
        assert stats["total_attempts"] == 2
        assert stats["resolved"] == 1
        assert stats["unresolved"] == 1
        assert stats["resolution_rate"] == 50.0
    
    @pytest.mark.asyncio
    async def test_strategy_breakdown(self, resolver, temp_project):
        """Test that strategy breakdown is tracked."""
        # Resolution with import path
        await resolver.resolve_import(
            target_name="DataProcessor",
            target_type="class",
            source_file=str(temp_project / "module_b.py"),
            source_language="python",
            import_path="module_a",
        )
        
        # Resolution with exact match
        await resolver.resolve_import(
            target_name="ConfigManager",
            target_type="class",
            source_file=str(temp_project / "module_c.py"),
            source_language="python",
        )
        
        stats = resolver.get_resolution_stats()
        assert "by_strategy" in stats
        assert stats["by_strategy"]["import_path"] >= 1
        assert stats["by_strategy"]["exact_match"] >= 1


class TestMultipleMatches:
    """Test handling of symbols with multiple definitions."""
    
    @pytest.mark.asyncio
    async def test_exported_symbol_preference(self, symbol_registry, temp_project):
        """Test that exported symbols are preferred over non-exported."""
        # Register same symbol twice - one exported, one not
        await symbol_registry.register(
            name="Helper",
            file_path=str(temp_project / "module_a.py"),
            entity_type="class",
            language="python",
            line_start=1,
            line_end=5,
            is_exported=False,
        )

        await symbol_registry.register(
            name="Helper",
            file_path=str(temp_project / "module_b.py"),
            entity_type="class",
            language="python",
            line_start=1,
            line_end=5,
            is_exported=True,
        )
        
        resolver = RelationshipResolver(
            symbol_registry=symbol_registry,
            project_root=str(temp_project),
        )
        
        result = await resolver.resolve_import(
            target_name="Helper",
            target_type="class",
            source_file=str(temp_project / "module_c.py"),
            source_language="python",
        )
        
        assert result is not None
        file_path, _, confidence = result
        # Should prefer the exported one
        assert "module_b.py" in file_path
        assert confidence >= 0.9



class TestStrategyExecutionOrder:
    """Test resolution strategy execution order and statistics.
    
    Feature: code-review-dec-2024-fixes
    """
    
    @pytest.mark.asyncio
    async def test_strategy_execution_order_property(self, resolver, temp_project):
        """Property 10: Resolution strategies execute in order.
        
        Feature: code-review-dec-2024-fixes, Property 10: Resolution strategies execute in order
        Validates: Requirements 6.2
        
        For any target resolution attempt, strategies should be tried in priority order
        (database → symbol → import_path → exact_match → module_path → proximity)
        until one succeeds.
        """
        
        # Track which strategies were called and in what order
        call_order = []
        
        # Create mock strategy methods that track calls
        async def mock_database(target_name, target_type, source_file, source_language, import_path):
            call_order.append("database")
            return None  # Fail to continue to next strategy
        
        async def mock_symbol(target_name, target_type, source_file, source_language, import_path):
            call_order.append("symbol")
            return None  # Fail to continue to next strategy
        
        async def mock_import_path(target_name, target_type, source_file, source_language, import_path):
            call_order.append("import_path")
            return None  # Fail to continue to next strategy
        
        async def mock_exact_match(target_name, target_type, source_file, source_language, import_path):
            call_order.append("exact_match")
            return None  # Fail to continue to next strategy
        
        async def mock_module_path(target_name, target_type, source_file, source_language, import_path):
            call_order.append("module_path")
            return None  # Fail to continue to next strategy
        
        async def mock_proximity(target_name, target_type, source_file, source_language, import_path):
            call_order.append("proximity")
            return ("test_file.py", "class", 0.8)  # Success
        
        # Replace strategy methods with mocks
        resolver._try_database_lookup = mock_database
        resolver._try_symbol_resolution = mock_symbol
        resolver._try_import_path = mock_import_path
        resolver._try_exact_match = mock_exact_match
        resolver._try_module_path = mock_module_path
        resolver._try_proximity = mock_proximity
        
        # Perform resolution
        result = await resolver.resolve_import(
            target_name="TestClass",
            target_type="class",
            source_file=str(temp_project / "module_a.py"),
            source_language="python",
            import_path="test.module",
        )
        
        # Verify result
        assert result is not None
        assert result == ("test_file.py", "class", 0.8)
        
        # Verify strategies were called in correct order
        expected_order = ["database", "symbol", "import_path", "exact_match", "module_path", "proximity"]
        assert call_order == expected_order, f"Expected {expected_order}, got {call_order}"
    
    @pytest.mark.asyncio
    async def test_strategy_stops_after_first_success(self, resolver, temp_project):
        """Property 10: Execution stops after first success.
        
        Feature: code-review-dec-2024-fixes, Property 10: Resolution strategies execute in order
        Validates: Requirements 6.2
        
        Verify that strategy execution stops after the first successful resolution.
        """
        call_order = []
        
        # Create mock strategy methods
        async def mock_database(target_name, target_type, source_file, source_language, import_path):
            call_order.append("database")
            return None  # Fail
        
        async def mock_symbol(target_name, target_type, source_file, source_language, import_path):
            call_order.append("symbol")
            return None  # Fail
        
        async def mock_import_path(target_name, target_type, source_file, source_language, import_path):
            call_order.append("import_path")
            return ("resolved_file.py", "class", 1.0)  # Success - should stop here
        
        async def mock_exact_match(target_name, target_type, source_file, source_language, import_path):
            call_order.append("exact_match")
            return ("should_not_reach.py", "class", 0.9)
        
        async def mock_module_path(target_name, target_type, source_file, source_language, import_path):
            call_order.append("module_path")
            return ("should_not_reach.py", "class", 0.9)
        
        async def mock_proximity(target_name, target_type, source_file, source_language, import_path):
            call_order.append("proximity")
            return ("should_not_reach.py", "class", 0.8)
        
        # Replace strategy methods
        resolver._try_database_lookup = mock_database
        resolver._try_symbol_resolution = mock_symbol
        resolver._try_import_path = mock_import_path
        resolver._try_exact_match = mock_exact_match
        resolver._try_module_path = mock_module_path
        resolver._try_proximity = mock_proximity
        
        # Perform resolution
        result = await resolver.resolve_import(
            target_name="TestClass",
            target_type="class",
            source_file=str(temp_project / "module_a.py"),
            source_language="python",
            import_path="test.module",
        )
        
        # Verify result is from import_path strategy
        assert result is not None
        assert result == ("resolved_file.py", "class", 1.0)
        
        # Verify only strategies up to and including import_path were called
        expected_order = ["database", "symbol", "import_path"]
        assert call_order == expected_order, f"Expected {expected_order}, got {call_order}"
        assert "exact_match" not in call_order
        assert "module_path" not in call_order
        assert "proximity" not in call_order
    
    @pytest.mark.asyncio
    async def test_strategy_order_with_different_success_points(self, resolver, temp_project):
        """Test strategy order when different strategies succeed.
        
        Feature: code-review-dec-2024-fixes, Property 10: Resolution strategies execute in order
        Validates: Requirements 6.2
        """
        # Test 1: Database succeeds first
        call_order_1 = []
        
        async def mock_database_success(target_name, target_type, source_file, source_language, import_path):
            call_order_1.append("database")
            return ("db_file.py", "class", 1.0)
        
        async def mock_other(target_name, target_type, source_file, source_language, import_path):
            call_order_1.append("other")
            return None
        
        resolver._try_database_lookup = mock_database_success
        resolver._try_symbol_resolution = mock_other
        resolver._try_import_path = mock_other
        resolver._try_exact_match = mock_other
        resolver._try_module_path = mock_other
        resolver._try_proximity = mock_other
        
        result = await resolver.resolve_import(
            target_name="Test1",
            target_type="class",
            source_file=str(temp_project / "module_a.py"),
            source_language="python",
        )
        
        assert result == ("db_file.py", "class", 1.0)
        assert call_order_1 == ["database"]
        
        # Clear cache before second test
        resolver.clear_cache()
        
        # Test 2: Exact match succeeds (4th strategy)
        call_order_2 = []
        
        async def mock_fail(target_name, target_type, source_file, source_language, import_path):
            call_order_2.append("fail")
            return None
        
        async def mock_exact_success(target_name, target_type, source_file, source_language, import_path):
            call_order_2.append("exact_match")
            return ("exact_file.py", "class", 1.0)
        
        resolver._try_database_lookup = mock_fail
        resolver._try_symbol_resolution = mock_fail
        resolver._try_import_path = mock_fail
        resolver._try_exact_match = mock_exact_success
        resolver._try_module_path = mock_other
        resolver._try_proximity = mock_other
        
        result = await resolver.resolve_import(
            target_name="Test2",
            target_type="class",
            source_file=str(temp_project / "module_a.py"),
            source_language="python",
        )
        
        assert result == ("exact_file.py", "class", 1.0)
        # Should have tried 3 fails before exact_match
        assert call_order_2 == ["fail", "fail", "fail", "exact_match"]


class TestStrategyStatistics:
    """Test resolution strategy statistics tracking.
    
    Feature: code-review-dec-2024-fixes
    """
    
    @pytest.mark.asyncio
    async def test_strategy_statistics_property(self, resolver, temp_project):
        """Property 11: Strategy statistics are tracked.
        
        Feature: code-review-dec-2024-fixes, Property 11: Strategy statistics are tracked
        Validates: Requirements 6.4
        
        For any successful resolution, the counter in self._stats["by_strategy"][strategy_name]
        should be incremented for the strategy that succeeded.
        """
        # Clear stats
        resolver._stats["by_strategy"] = {
            "database": 0,
            "symbol": 0,
            "import_path": 0,
            "exact_match": 0,
            "module_path": 0,
            "proximity": 0,
        }
        
        # Create mocks that succeed at different strategies
        async def mock_database_success(target_name, target_type, source_file, source_language, import_path):
            return ("db_file.py", "class", 1.0)
        
        async def mock_fail(target_name, target_type, source_file, source_language, import_path):
            return None
        
        async def mock_import_success(target_name, target_type, source_file, source_language, import_path):
            return ("import_file.py", "class", 1.0)
        
        async def mock_proximity_success(target_name, target_type, source_file, source_language, import_path):
            return ("proximity_file.py", "class", 0.8)
        
        # Test 1: Database strategy succeeds
        resolver._try_database_lookup = mock_database_success
        resolver._try_symbol_resolution = mock_fail
        resolver._try_import_path = mock_fail
        resolver._try_exact_match = mock_fail
        resolver._try_module_path = mock_fail
        resolver._try_proximity = mock_fail
        
        await resolver.resolve_import(
            target_name="Test1",
            target_type="class",
            source_file=str(temp_project / "module_a.py"),
            source_language="python",
        )
        
        assert resolver._stats["by_strategy"]["database"] == 1
        assert resolver._stats["by_strategy"]["symbol"] == 0
        assert resolver._stats["by_strategy"]["import_path"] == 0
        
        # Test 2: Import path strategy succeeds
        resolver._try_database_lookup = mock_fail
        resolver._try_symbol_resolution = mock_fail
        resolver._try_import_path = mock_import_success
        
        await resolver.resolve_import(
            target_name="Test2",
            target_type="class",
            source_file=str(temp_project / "module_a.py"),
            source_language="python",
            import_path="test.module",
        )
        
        assert resolver._stats["by_strategy"]["database"] == 1  # Unchanged
        assert resolver._stats["by_strategy"]["import_path"] == 1  # Incremented
        
        # Test 3: Proximity strategy succeeds
        resolver._try_database_lookup = mock_fail
        resolver._try_symbol_resolution = mock_fail
        resolver._try_import_path = mock_fail
        resolver._try_exact_match = mock_fail
        resolver._try_module_path = mock_fail
        resolver._try_proximity = mock_proximity_success
        
        await resolver.resolve_import(
            target_name="Test3",
            target_type="class",
            source_file=str(temp_project / "module_a.py"),
            source_language="python",
        )
        
        assert resolver._stats["by_strategy"]["proximity"] == 1  # Incremented
        
        # Verify each successful resolution incremented exactly one counter
        stats = resolver.get_resolution_stats()
        total_strategy_resolutions = sum(stats["by_strategy"].values())
        assert total_strategy_resolutions == 3  # 3 successful resolutions
    
    @pytest.mark.asyncio
    async def test_each_resolution_increments_one_counter(self, resolver, temp_project):
        """Verify each successful resolution increments exactly one counter.
        
        Feature: code-review-dec-2024-fixes, Property 11: Strategy statistics are tracked
        Validates: Requirements 6.4
        """
        # Clear stats
        initial_stats = {
            "database": 0,
            "symbol": 0,
            "import_path": 0,
            "exact_match": 0,
            "module_path": 0,
            "proximity": 0,
        }
        resolver._stats["by_strategy"] = initial_stats.copy()
        
        # Mock a successful resolution at import_path
        async def mock_fail(target_name, target_type, source_file, source_language, import_path):
            return None
        
        async def mock_import_success(target_name, target_type, source_file, source_language, import_path):
            return ("import_file.py", "class", 1.0)
        
        resolver._try_database_lookup = mock_fail
        resolver._try_symbol_resolution = mock_fail
        resolver._try_import_path = mock_import_success
        resolver._try_exact_match = mock_fail
        resolver._try_module_path = mock_fail
        resolver._try_proximity = mock_fail
        
        # Get stats before
        stats_before = resolver._stats["by_strategy"].copy()
        
        # Perform resolution
        await resolver.resolve_import(
            target_name="Test",
            target_type="class",
            source_file=str(temp_project / "module_a.py"),
            source_language="python",
            import_path="test.module",
        )
        
        # Get stats after
        stats_after = resolver._stats["by_strategy"].copy()
        
        # Calculate differences
        differences = {
            strategy: stats_after[strategy] - stats_before[strategy]
            for strategy in stats_before.keys()
        }
        
        # Verify exactly one counter was incremented
        incremented_strategies = [s for s, diff in differences.items() if diff > 0]
        assert len(incremented_strategies) == 1, f"Expected exactly 1 strategy incremented, got {incremented_strategies}"
        assert incremented_strategies[0] == "import_path"
        assert differences["import_path"] == 1
        
        # Verify all other counters unchanged
        for strategy in ["database", "symbol", "exact_match", "module_path", "proximity"]:
            assert differences[strategy] == 0, f"Strategy {strategy} should not have been incremented"
