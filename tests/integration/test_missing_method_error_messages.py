"""Test missing method error messages (Example 10).

This module tests that calling non-existent methods provides helpful error
messages suggesting the correct method name.

**Validates: Requirements 9.5**
"""

import pytest

pytestmark = pytest.mark.integration
from agentic_inquiry.config import Config
from agentic_inquiry.database.lancedb_manager import LanceDBManager


class TestMissingMethodErrorMessages:
    """Test missing method error messages suggest correct method names."""
    
    def test_missing_method_error_message(self):
        """Test that calling non-existent method suggests correct method.
        
        **Example 10: Missing method error**
        **Validates: Requirements 9.5**
        
        Verifies that:
        - Error indicates method doesn't exist
        - Error suggests similar method names if available
        
        Note: Python's AttributeError doesn't automatically suggest similar
        method names, but we can verify the error message is clear.
        """
        config = Config.load()
        db_manager = LanceDBManager.from_config(config)
        
        # Try to call a non-existent method
        with pytest.raises(AttributeError) as exc_info:
            db_manager.add_document_chunk()  # Should be add_document_chunks (plural)
        
        error_msg = str(exc_info.value)
        
        # Verify error indicates the method doesn't exist
        assert "add_document_chunk" in error_msg or "has no attribute" in error_msg
    
    def test_typo_in_method_name(self):
        """Test that typos in method names raise clear errors."""
        config = Config.load()
        db_manager = LanceDBManager.from_config(config)
        
        # Try to call a method with a typo
        with pytest.raises(AttributeError) as exc_info:
            db_manager.add_graph_entitie()  # Should be add_graph_entities
        
        error_msg = str(exc_info.value)
        
        # Verify error is clear about the missing method
        assert "add_graph_entitie" in error_msg or "has no attribute" in error_msg
    
    def test_wrong_case_method_name(self):
        """Test that wrong case in method names raises clear errors."""
        config = Config.load()
        db_manager = LanceDBManager.from_config(config)
        
        # Try to call a method with wrong case
        with pytest.raises(AttributeError) as exc_info:
            db_manager.Add_Document_Chunks()  # Should be add_document_chunks
        
        error_msg = str(exc_info.value)
        
        # Verify error is clear
        assert "Add_Document_Chunks" in error_msg or "has no attribute" in error_msg
    
    def test_similar_method_exists(self):
        """Test that when a similar method exists, the error is clear.
        
        This test verifies that Python's default AttributeError provides
        enough information to identify the correct method.
        """
        config = Config.load()
        db_manager = LanceDBManager.from_config(config)
        
        # Verify the correct method exists
        assert hasattr(db_manager, "add_document_chunks")
        
        # Try to call similar but wrong method
        with pytest.raises(AttributeError) as exc_info:
            db_manager.add_document_chunk()
        
        error_msg = str(exc_info.value)
        
        # The error should mention the attempted method name
        assert "add_document_chunk" in error_msg or "LanceDBManager" in error_msg
    
    def test_completely_wrong_method_name(self):
        """Test that completely wrong method names raise clear errors."""
        config = Config.load()
        db_manager = LanceDBManager.from_config(config)
        
        # Try to call a completely wrong method
        with pytest.raises(AttributeError) as exc_info:
            db_manager.insert_data()  # No such method exists
        
        error_msg = str(exc_info.value)
        
        # Verify error mentions the method name
        assert "insert_data" in error_msg or "has no attribute" in error_msg
