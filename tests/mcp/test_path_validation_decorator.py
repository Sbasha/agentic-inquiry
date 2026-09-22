"""Property-based tests for path validation decorator."""

import pytest

pytestmark = pytest.mark.unit

import tempfile
from pathlib import Path
from hypothesis import given, settings, strategies as st

from agent_vault.mcp.utils.validation import (
    PathValidationError,
    validate_path,
)


# Helper class for testing the decorator
class MockPipeline:
    """Mock class to test the validate_path decorator."""
    
    def __init__(self, project_root: str):
        self.project_root = project_root
    
    @validate_path()
    async def async_method(self, file_path: str) -> str:
        """Async method that should have validated path."""
        return file_path
    
    @validate_path()
    def sync_method(self, file_path: str) -> str:
        """Sync method that should have validated path."""
        return file_path


# Strategy for generating file paths with traversal attempts
@st.composite
def traversal_paths(draw):
    """Generate paths that attempt directory traversal."""
    strategies = [
        # Relative traversal
        st.just("../etc/passwd"),
        st.just("../../etc/passwd"),
        st.just("../../../etc/passwd"),
        st.just("subdir/../../etc/passwd"),
        st.just("./../../etc/passwd"),
        # Absolute paths (likely outside project)
        st.just("/etc/passwd"),
        st.just("/tmp/secret"),
        st.just("/root/.ssh/id_rsa"),
        # Mixed traversal
        st.just("valid/../../../etc/passwd"),
        st.just("a/b/c/../../../../etc/passwd"),
    ]
    return draw(st.one_of(*strategies))


@st.composite
def valid_relative_paths(draw):
    """Generate valid relative paths within project."""
    # Generate path components (no dots or slashes)
    num_components = draw(st.integers(min_value=1, max_value=5))
    components = []
    for _ in range(num_components):
        component = draw(st.text(
            alphabet=st.characters(
                whitelist_categories=('Lu', 'Ll', 'Nd'),
                whitelist_characters='_-'
            ),
            min_size=1,
            max_size=20
        ))
        components.append(component)
    
    # Add a filename
    filename = draw(st.text(
        alphabet=st.characters(
            whitelist_categories=('Lu', 'Ll', 'Nd'),
            whitelist_characters='_-.'
        ),
        min_size=1,
        max_size=30
    ))
    
    return "/".join(components) + "/" + filename


class TestPathValidationDecoratorProperties:
    """Property-based tests for validate_path decorator."""
    
    # Feature: code-review-dec-2024-fixes, Property 1: Path validation prevents traversal
    @settings(max_examples=100)
    @given(path=traversal_paths())
    @pytest.mark.asyncio
    async def test_decorator_prevents_traversal_async(self, path):
        """Property: For any path with traversal attempts, decorator raises PathValidationError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            pipeline = MockPipeline(tmp_dir)
            
            with pytest.raises(PathValidationError) as exc_info:
                await pipeline.async_method(path)
            
            # Verify error message mentions security constraint
            error_msg = str(exc_info.value)
            assert "outside allowed directory" in error_msg or "Security constraint" in error_msg
    
    # Feature: code-review-dec-2024-fixes, Property 1: Path validation prevents traversal
    @settings(max_examples=100)
    @given(path=traversal_paths())
    def test_decorator_prevents_traversal_sync(self, path):
        """Property: For any path with traversal attempts, decorator raises PathValidationError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            pipeline = MockPipeline(tmp_dir)
            
            with pytest.raises(PathValidationError) as exc_info:
                pipeline.sync_method(path)
            
            # Verify error message mentions security constraint
            error_msg = str(exc_info.value)
            assert "outside allowed directory" in error_msg or "Security constraint" in error_msg
    
    # Feature: code-review-dec-2024-fixes, Property 1: Path validation prevents traversal
    @settings(max_examples=100)
    @given(path=valid_relative_paths())
    @pytest.mark.asyncio
    async def test_decorator_allows_valid_paths_async(self, path):
        """Property: For any valid relative path, decorator allows it through."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            pipeline = MockPipeline(tmp_dir)
            
            # Should not raise
            result = await pipeline.async_method(path)
            
            # Result should be an absolute path within project
            result_path = Path(result)
            assert result_path.is_absolute()
            
            # Verify it's within the project root
            tmp_path = Path(tmp_dir).resolve()
            try:
                result_path.relative_to(tmp_path)
            except ValueError:
                pytest.fail(f"Validated path {result_path} is not within project root {tmp_path}")
    
    # Feature: code-review-dec-2024-fixes, Property 1: Path validation prevents traversal
    @settings(max_examples=100)
    @given(path=valid_relative_paths())
    def test_decorator_allows_valid_paths_sync(self, path):
        """Property: For any valid relative path, decorator allows it through."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            pipeline = MockPipeline(tmp_dir)
            
            # Should not raise
            result = pipeline.sync_method(path)
            
            # Result should be an absolute path within project
            result_path = Path(result)
            assert result_path.is_absolute()
            
            # Verify it's within the project root
            tmp_path = Path(tmp_dir).resolve()
            try:
                result_path.relative_to(tmp_path)
            except ValueError:
                pytest.fail(f"Validated path {result_path} is not within project root {tmp_path}")
    
    @pytest.mark.asyncio
    async def test_decorator_with_absolute_path_outside_project(self, tmp_path):
        """Test that absolute paths outside project are rejected."""
        pipeline = MockPipeline(str(tmp_path))
        
        # Try various absolute paths that are likely outside project
        outside_paths = ["/etc/passwd", "/tmp/test", "/root/secret"]
        
        for path in outside_paths:
            with pytest.raises(PathValidationError):
                await pipeline.async_method(path)
    
    @pytest.mark.asyncio
    async def test_decorator_with_absolute_path_inside_project(self, tmp_path):
        """Test that absolute paths inside project are accepted."""
        pipeline = MockPipeline(str(tmp_path))
        
        # Create a file inside project
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        
        # Use absolute path
        result = await pipeline.async_method(str(test_file))
        
        # Should be accepted and normalized
        assert Path(result) == test_file.resolve()
    
    def test_decorator_missing_project_root_attribute(self):
        """Test that decorator raises AttributeError if project_root is missing."""
        
        class BadPipeline:
            # Missing project_root attribute
            
            @validate_path()
            def method(self, file_path: str) -> str:
                return file_path
        
        pipeline = BadPipeline()
        
        with pytest.raises(AttributeError) as exc_info:
            pipeline.method("test.txt")
        
        assert "project_root" in str(exc_info.value)
    
    def test_decorator_with_custom_attribute_name(self, tmp_path):
        """Test that decorator works with custom project root attribute name."""
        
        class CustomPipeline:
            def __init__(self, root_dir: str):
                self.root_dir = root_dir
            
            @validate_path(project_root_attr="root_dir")
            def method(self, file_path: str) -> str:
                return file_path
        
        pipeline = CustomPipeline(str(tmp_path))
        
        # Should work with custom attribute
        result = pipeline.method("test.txt")
        assert Path(result).is_absolute()



class TestPathValidationDecoratorErrorMessages:
    """Unit tests for path validation decorator error messages."""
    
    # Feature: code-review-dec-2024-fixes, Property 2: Invalid paths raise correct exception
    @pytest.mark.asyncio
    async def test_traversal_path_error_message(self, tmp_path):
        """Test that ../etc/passwd raises PathValidationError with security message."""
        pipeline = MockPipeline(str(tmp_path))
        
        with pytest.raises(PathValidationError) as exc_info:
            await pipeline.async_method("../etc/passwd")
        
        error_msg = str(exc_info.value)
        # Verify error message explains security constraint
        assert "Security constraint violation" in error_msg or "outside allowed directory" in error_msg
        assert "security" in error_msg.lower()
    
    # Feature: code-review-dec-2024-fixes, Property 2: Invalid paths raise correct exception
    @pytest.mark.asyncio
    async def test_absolute_path_error_message(self, tmp_path):
        """Test that /etc/passwd raises PathValidationError with security message."""
        pipeline = MockPipeline(str(tmp_path))
        
        with pytest.raises(PathValidationError) as exc_info:
            await pipeline.async_method("/etc/passwd")
        
        error_msg = str(exc_info.value)
        # Verify error message explains security constraint
        assert "Security constraint violation" in error_msg or "outside allowed directory" in error_msg
        assert "security" in error_msg.lower()
    
    # Feature: code-review-dec-2024-fixes, Property 2: Invalid paths raise correct exception
    def test_sync_method_error_message(self, tmp_path):
        """Test that sync methods also raise PathValidationError with proper message."""
        pipeline = MockPipeline(str(tmp_path))
        
        with pytest.raises(PathValidationError) as exc_info:
            pipeline.sync_method("../etc/passwd")
        
        error_msg = str(exc_info.value)
        # Verify error message explains security constraint
        assert "Security constraint violation" in error_msg or "outside allowed directory" in error_msg
        assert "security" in error_msg.lower()
    
    @pytest.mark.asyncio
    async def test_error_message_includes_helpful_guidance(self, tmp_path):
        """Test that error messages include helpful guidance for users."""
        pipeline = MockPipeline(str(tmp_path))
        
        with pytest.raises(PathValidationError) as exc_info:
            await pipeline.async_method("../../secret")
        
        error_msg = str(exc_info.value)
        # Should include guidance about using relative paths
        assert "relative path" in error_msg.lower() or "project" in error_msg.lower()
