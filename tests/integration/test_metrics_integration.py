"""Tests for metrics system integration.

Verifies that metrics are correctly tracked and reported across the system.
"""

from agentic_inquiry.metrics import (
    get_metrics_tracker,
    reset_metrics,
)


class TestMetricsDocumentation:
    """Document how metrics tracking works in the system."""
    
    def test_metrics_usage_pattern(self):
        """Document the usage pattern for metrics tracking."""
        # This test documents how components use metrics
        
        # 1. Components get the global metrics tracker
        tracker = get_metrics_tracker()
        
        # 2. They use track_latency context manager for operations
        with tracker.track_latency("example_operation"):
            # Perform operation
            pass
        
        # 3. Metrics are automatically recorded
        metrics = tracker.get_latency_metrics("example_operation")
        assert metrics.count == 1
        assert metrics.total_time > 0
        
        # 4. Get all metrics
        all_metrics = tracker.get_all_metrics()
        assert "example_operation" in all_metrics['latency']
        
        # 5. Get summary
        summary = tracker.get_summary()
        assert "latency_metrics" in summary
        assert "total_operations" in summary
        
        # 6. Reset metrics
        reset_metrics()
        # After reset, get_metrics_tracker() returns a new instance with no metrics
        new_tracker = get_metrics_tracker()
        assert len(new_tracker._latency_metrics) == 0
    
    def test_search_service_has_metrics_method(self):
        """Verify SearchService has get_metrics method."""
        from agentic_inquiry.search.service import SearchService
        
        # Verify the method exists
        assert hasattr(SearchService, 'get_metrics')
        assert callable(getattr(SearchService, 'get_metrics'))
    
    def test_lancedb_manager_has_metrics_method(self):
        """Verify LanceDBManager has get_metrics method."""
        from agentic_inquiry.database.lancedb_manager import LanceDBManager
        
        # Verify the method exists
        assert hasattr(LanceDBManager, 'get_metrics')
        assert callable(getattr(LanceDBManager, 'get_metrics'))
    
    def test_relationship_resolver_has_metrics(self):
        """Verify RelationshipResolver has metrics tracking."""
        from agentic_inquiry.indexing.relationship_resolver import RelationshipResolver
        
        # Verify the methods exist
        assert hasattr(RelationshipResolver, 'cache_hit_rate')
        assert hasattr(RelationshipResolver, 'get_resolution_stats')
    
    def test_document_cache_has_metrics(self):
        """Verify DocumentCache has metrics tracking."""
        from agentic_inquiry.cache.document_cache import DocumentCache
        
        # Verify the method exists
        assert hasattr(DocumentCache, 'stats')
        assert callable(getattr(DocumentCache, 'stats'))


# Note: Full integration tests with actual database operations would require
# more complex async fixture setup. The core metrics functionality is
# thoroughly tested in test_metrics.py, and this file documents the integration
# points. For actual usage verification, see:
# - agentic_inquiry/search/service.py (SearchService methods use track_latency)
# - agentic_inquiry/database/lancedb_manager.py (LanceDBManager methods use track_latency)
# - agentic_inquiry/indexing/relationship_resolver.py (tracks resolution stats)
# - agentic_inquiry/cache/document_cache.py (tracks cache hits/misses)
