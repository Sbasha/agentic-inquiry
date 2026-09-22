"""Tests for MCP path validation utilities."""

import pytest

pytestmark = pytest.mark.unit

from pathlib import Path

from agent_vault.mcp.utils.validation import (
    ColumnNameValidationError,
    EntityNameValidationError,
    PathValidationError,
    ProjectIDValidationError,
    QueryValidationError,
    validate_column_name,
    validate_column_names,
    validate_entity_name,
    validate_file_path,
    validate_project_id,
    validate_query_length,
    validate_table_name,
    KNOWN_TABLE_NAMES,
    MAX_ENTITY_NAME_LENGTH,
    MAX_QUERY_LENGTH,
    MIN_ENTITY_NAME_LENGTH,
    MIN_QUERY_LENGTH,
    FORBIDDEN_ENTITY_CHARS,
)


class TestPathValidation:
    """Test path validation security features."""
    
    def test_valid_path_within_base(self, tmp_path):
        """Test that valid paths within base directory are accepted."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        
        # Validate the path
        result = validate_file_path(test_file, tmp_path, must_exist=True)
        
        assert result == test_file.resolve()
        assert result.exists()
    
    def test_valid_relative_path(self, tmp_path):
        """Test that relative paths within base are accepted."""
        # Create subdirectory and file
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        test_file = subdir / "test.txt"
        test_file.write_text("test content")
        
        # Validate using relative path from base
        relative_path = "subdir/test.txt"
        result = validate_file_path(relative_path, tmp_path, must_exist=True)
        
        assert result == test_file.resolve()
    
    def test_directory_traversal_rejected(self, tmp_path):
        """Test that directory traversal attempts are rejected."""
        # Try to access parent directory
        malicious_path = "../etc/passwd"
        
        with pytest.raises(PathValidationError) as exc_info:
            validate_file_path(malicious_path, tmp_path)
        
        assert "outside allowed directory" in str(exc_info.value)
    
    def test_absolute_path_outside_base_rejected(self, tmp_path):
        """Test that absolute paths outside base are rejected."""
        # Try to access a path outside the base
        outside_path = Path("/etc/passwd")
        
        with pytest.raises(PathValidationError) as exc_info:
            validate_file_path(outside_path, tmp_path)
        
        assert "outside allowed directory" in str(exc_info.value)
    
    def test_complex_traversal_rejected(self, tmp_path):
        """Test that complex directory traversal sequences are rejected."""
        # Create a subdirectory
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        
        # Try to traverse up and out
        malicious_path = "subdir/../../etc/passwd"
        
        with pytest.raises(PathValidationError) as exc_info:
            validate_file_path(malicious_path, tmp_path)
        
        assert "outside allowed directory" in str(exc_info.value)
    
    def test_non_existent_path_with_must_exist(self, tmp_path):
        """Test that non-existent paths are rejected when must_exist=True."""
        non_existent = tmp_path / "does_not_exist.txt"
        
        with pytest.raises(PathValidationError) as exc_info:
            validate_file_path(non_existent, tmp_path, must_exist=True)
        
        assert "does not exist" in str(exc_info.value)
    
    def test_non_existent_path_without_must_exist(self, tmp_path):
        """Test that non-existent paths are accepted when must_exist=False."""
        non_existent = tmp_path / "does_not_exist.txt"
        
        # Should not raise
        result = validate_file_path(non_existent, tmp_path, must_exist=False)
        
        assert result == non_existent.resolve()
    
    def test_symlink_traversal_rejected(self, tmp_path):
        """Test that symlinks pointing outside base are rejected."""
        # Create a symlink pointing outside the base
        outside_dir = tmp_path.parent / "outside"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "secret.txt"
        outside_file.write_text("secret")
        
        symlink = tmp_path / "link_to_outside"
        try:
            symlink.symlink_to(outside_file)
        except OSError:
            # Skip test if symlinks not supported (e.g., Windows without admin)
            pytest.skip("Symlinks not supported on this system")
        
        with pytest.raises(PathValidationError) as exc_info:
            validate_file_path(symlink, tmp_path, must_exist=True)
        
        assert "outside allowed directory" in str(exc_info.value)
    
    def test_symlink_within_base_accepted(self, tmp_path):
        """Test that symlinks within base directory are accepted."""
        # Create a file and symlink within base
        real_file = tmp_path / "real.txt"
        real_file.write_text("content")
        
        symlink = tmp_path / "link.txt"
        try:
            symlink.symlink_to(real_file)
        except OSError:
            # Skip test if symlinks not supported
            pytest.skip("Symlinks not supported on this system")
        
        # Should not raise
        result = validate_file_path(symlink, tmp_path, must_exist=True)
        
        # Result should be the resolved path (pointing to real file)
        assert result == real_file.resolve()
    
    def test_nested_directory_path(self, tmp_path):
        """Test validation of deeply nested directory paths."""
        # Create nested structure
        nested = tmp_path / "a" / "b" / "c" / "d"
        nested.mkdir(parents=True)
        test_file = nested / "test.txt"
        test_file.write_text("nested content")
        
        # Validate the nested path
        result = validate_file_path(test_file, tmp_path, must_exist=True)
        
        assert result == test_file.resolve()
    
    def test_path_with_dots_in_name(self, tmp_path):
        """Test that paths with dots in filenames are handled correctly."""
        # Create file with dots in name
        test_file = tmp_path / "my.test.file.txt"
        test_file.write_text("content")
        
        # Should not raise (dots in filename are not traversal)
        result = validate_file_path(test_file, tmp_path, must_exist=True)
        
        assert result == test_file.resolve()
    
    def test_returns_absolute_path(self, tmp_path):
        """Test that function always returns absolute paths."""
        # Use relative path
        relative = "test.txt"
        
        result = validate_file_path(relative, tmp_path, must_exist=False)
        
        assert result.is_absolute()
        assert str(tmp_path.resolve()) in str(result)



class TestProjectIDValidation:
    """Test project ID validation."""
    
    def test_valid_lowercase_project_id(self):
        """Test that valid lowercase project IDs are accepted."""
        valid_ids = [
            "my-project",
            "project_123",
            "my_project",
            "test-app-1",
            "app123",
            "a",
            "project-with-many-hyphens",
            "project_with_many_underscores"
        ]
        
        for project_id in valid_ids:
            result = validate_project_id(project_id)
            assert result == project_id
    
    def test_valid_uppercase_normalized(self):
        """Test that uppercase project IDs are normalized to lowercase."""
        test_cases = [
            ("My-Project", "my-project"),
            ("PROJECT_123", "project_123"),
            ("My_Project", "my_project"),
            ("TEST-APP-1", "test-app-1"),
            ("MixedCase123", "mixedcase123")
        ]
        
        for input_id, expected in test_cases:
            result = validate_project_id(input_id, normalize=True)
            assert result == expected
    
    def test_uppercase_without_normalization(self):
        """Test that uppercase IDs are preserved when normalize=False."""
        test_ids = ["My-Project", "PROJECT_123", "MixedCase"]
        
        for project_id in test_ids:
            result = validate_project_id(project_id, normalize=False)
            assert result == project_id
    
    def test_invalid_characters_spaces(self):
        """Test that project IDs with spaces are rejected."""
        invalid_ids = [
            "my project",
            "project 123",
            "test app",
            " project",
            "project "
        ]
        
        for project_id in invalid_ids:
            with pytest.raises(ProjectIDValidationError) as exc_info:
                validate_project_id(project_id)
            
            assert "invalid characters" in str(exc_info.value).lower()
            assert "examples" in str(exc_info.value).lower()
    
    def test_invalid_characters_special(self):
        """Test that project IDs with special characters are rejected."""
        invalid_ids = [
            "project!",
            "my@project",
            "test#app",
            "project$123",
            "app%test",
            "project&test",
            "test*app",
            "project+test",
            "app=test",
            "project[test]",
            "test{app}",
            "project|test",
            "test\\app",
            "project:test",
            "test;app",
            "project'test",
            'test"app',
            "project<test>",
            "test,app",
            "project.test",
            "test?app",
            "project/test"
        ]
        
        for project_id in invalid_ids:
            with pytest.raises(ProjectIDValidationError) as exc_info:
                validate_project_id(project_id)
            
            error_msg = str(exc_info.value).lower()
            assert "invalid characters" in error_msg
            assert "alphanumeric" in error_msg or "examples" in error_msg
    
    def test_empty_project_id(self):
        """Test that empty project IDs are rejected."""
        with pytest.raises(ProjectIDValidationError) as exc_info:
            validate_project_id("")
        
        assert "cannot be empty" in str(exc_info.value).lower()
        assert "examples" in str(exc_info.value).lower()
    
    def test_none_project_id(self):
        """Test that None project IDs are rejected."""
        with pytest.raises(ProjectIDValidationError) as exc_info:
            validate_project_id(None)
        
        assert "cannot be empty" in str(exc_info.value).lower()
    
    def test_length_constraint_too_long(self):
        """Test that project IDs exceeding 64 characters are rejected."""
        # Create a 65-character project ID
        too_long = "a" * 65
        
        with pytest.raises(ProjectIDValidationError) as exc_info:
            validate_project_id(too_long)
        
        error_msg = str(exc_info.value).lower()
        assert "exceeds maximum length" in error_msg or "64 characters" in error_msg
        assert "examples" in error_msg
    
    def test_length_constraint_boundary(self):
        """Test boundary cases for length constraints."""
        # Exactly 64 characters (should pass)
        exactly_64 = "a" * 64
        result = validate_project_id(exactly_64)
        assert result == exactly_64
        
        # 63 characters (should pass)
        chars_63 = "a" * 63
        result = validate_project_id(chars_63)
        assert result == chars_63
        
        # 1 character (should pass)
        single_char = "a"
        result = validate_project_id(single_char)
        assert result == single_char
    
    def test_error_message_quality(self):
        """Test that error messages include helpful examples."""
        # Test with invalid characters
        with pytest.raises(ProjectIDValidationError) as exc_info:
            validate_project_id("invalid project!")
        
        error_msg = str(exc_info.value)
        # Should include examples
        assert "my-project" in error_msg or "project_123" in error_msg or "my_project" in error_msg
        
        # Test with too long
        with pytest.raises(ProjectIDValidationError) as exc_info:
            validate_project_id("a" * 65)
        
        error_msg = str(exc_info.value)
        # Should include examples
        assert "my-project" in error_msg or "proj-123" in error_msg or "my_app" in error_msg
    
    def test_mixed_valid_characters(self):
        """Test project IDs with mixed valid characters."""
        valid_ids = [
            "my-project_123",
            "test_app-v2",
            "app-123_test",
            "project-2024_q1",
            "test_123-abc"
        ]
        
        for project_id in valid_ids:
            result = validate_project_id(project_id)
            assert result == project_id
    
    def test_normalization_preserves_hyphens_underscores(self):
        """Test that normalization preserves hyphens and underscores."""
        test_cases = [
            ("My-Project_123", "my-project_123"),
            ("TEST_APP-V2", "test_app-v2"),
            ("Project-2024_Q1", "project-2024_q1")
        ]

        for input_id, expected in test_cases:
            result = validate_project_id(input_id, normalize=True)
            assert result == expected


class TestQueryValidation:
    """Test query length validation for DoS protection (S5-001)."""

    def test_constants_defined(self):
        """Test that query length constants are defined correctly."""
        assert MAX_QUERY_LENGTH == 10_000
        assert MIN_QUERY_LENGTH == 1

    def test_valid_short_query(self):
        """Test that valid short queries are accepted."""
        valid_queries = [
            "search",
            "how to authenticate",
            "find all classes with Factory pattern",
            "authentication error handling in the API layer"
        ]

        for query in valid_queries:
            result = validate_query_length(query)
            assert result == query

    def test_empty_query_rejected(self):
        """Test that empty queries are rejected."""
        with pytest.raises(QueryValidationError) as exc_info:
            validate_query_length("")

        error_msg = str(exc_info.value)
        assert "cannot be empty" in error_msg.lower()
        assert "example" in error_msg.lower()

    def test_whitespace_only_query_rejected(self):
        """Test that whitespace-only queries are rejected."""
        whitespace_queries = [
            "   ",
            "\t\t",
            "\n\n",
            "   \t\n   "
        ]

        for query in whitespace_queries:
            with pytest.raises(QueryValidationError) as exc_info:
                validate_query_length(query)
            assert "cannot be empty" in str(exc_info.value).lower()

    def test_none_query_rejected(self):
        """Test that None queries are rejected."""
        with pytest.raises(QueryValidationError) as exc_info:
            validate_query_length(None)

        error_msg = str(exc_info.value)
        assert "cannot be none" in error_msg.lower()
        assert "example" in error_msg.lower()

    def test_long_query_truncated_by_default(self):
        """Test that long queries are truncated with warning when truncate=True."""
        # Create a query longer than MAX_QUERY_LENGTH
        long_query = "x" * (MAX_QUERY_LENGTH + 5000)

        result = validate_query_length(long_query, truncate=True)

        assert len(result) == MAX_QUERY_LENGTH
        assert result == "x" * MAX_QUERY_LENGTH

    def test_long_query_raises_when_truncate_false(self):
        """Test that long queries raise error when truncate=False."""
        long_query = "x" * (MAX_QUERY_LENGTH + 1)

        with pytest.raises(QueryValidationError) as exc_info:
            validate_query_length(long_query, truncate=False)

        error_msg = str(exc_info.value)
        assert "exceeds maximum length" in error_msg.lower()
        assert str(MAX_QUERY_LENGTH) in error_msg

    def test_exact_max_length_accepted(self):
        """Test that queries at exactly MAX_QUERY_LENGTH are accepted."""
        exact_query = "x" * MAX_QUERY_LENGTH

        result = validate_query_length(exact_query)

        assert result == exact_query
        assert len(result) == MAX_QUERY_LENGTH

    def test_one_less_than_max_accepted(self):
        """Test that queries one less than MAX_QUERY_LENGTH are accepted."""
        query = "x" * (MAX_QUERY_LENGTH - 1)

        result = validate_query_length(query)

        assert result == query

    def test_custom_max_length(self):
        """Test that custom max_length is respected."""
        custom_max = 100
        long_query = "x" * 150

        result = validate_query_length(long_query, max_length=custom_max, truncate=True)

        assert len(result) == custom_max

        # Test without truncation
        with pytest.raises(QueryValidationError):
            validate_query_length(long_query, max_length=custom_max, truncate=False)

    def test_custom_field_name_in_error(self):
        """Test that custom field_name appears in error messages."""
        with pytest.raises(QueryValidationError) as exc_info:
            validate_query_length("", field_name="search_query")

        error_msg = str(exc_info.value)
        assert "search_query" in error_msg.lower()

    def test_query_stripped_of_whitespace(self):
        """Test that leading/trailing whitespace is stripped."""
        query_with_whitespace = "   actual query   "

        result = validate_query_length(query_with_whitespace)

        assert result == "actual query"
        assert result == query_with_whitespace.strip()

    def test_single_character_query_accepted(self):
        """Test that single character queries are accepted."""
        single_char = "a"

        result = validate_query_length(single_char)

        assert result == single_char

    def test_unicode_query_accepted(self):
        """Test that unicode queries are handled correctly."""
        unicode_queries = [
            "搜索功能",  # Chinese
            "αβγδε",   # Greek
            "日本語テスト",  # Japanese
            "émoji 😀 query"  # Emoji
        ]

        for query in unicode_queries:
            result = validate_query_length(query)
            assert result == query

    def test_error_message_includes_examples(self):
        """Test that error messages include helpful examples."""
        with pytest.raises(QueryValidationError) as exc_info:
            validate_query_length("")

        error_msg = str(exc_info.value)
        # Should include examples
        assert "authentication" in error_msg.lower() or "example" in error_msg.lower()


class TestEntityNameValidation:
    """Test entity name validation for security (S5-004)."""

    def test_constants_defined(self):
        """Test that entity name constants are defined correctly."""
        assert MAX_ENTITY_NAME_LENGTH == 500
        assert MIN_ENTITY_NAME_LENGTH == 1
        assert "/" in FORBIDDEN_ENTITY_CHARS
        assert "\\" in FORBIDDEN_ENTITY_CHARS
        assert "\x00" in FORBIDDEN_ENTITY_CHARS

    def test_valid_entity_names(self):
        """Test that valid entity names are accepted."""
        valid_names = [
            "MyClass",
            "my_function",
            "process_data",
            "Config",
            "SearchService",
            "authenticate",
            "__init__",
            "_private_method",
            "CamelCaseClass",
            "snake_case_function",
            "mixedCase123",
            "Class_With_Numbers_123",
        ]

        for name in valid_names:
            result = validate_entity_name(name)
            assert result == name

    def test_empty_entity_rejected(self):
        """Test that empty entity names are rejected."""
        with pytest.raises(EntityNameValidationError) as exc_info:
            validate_entity_name("")

        error_msg = str(exc_info.value)
        assert "cannot be empty" in error_msg.lower()
        assert "example" in error_msg.lower()

    def test_whitespace_only_entity_rejected(self):
        """Test that whitespace-only entity names are rejected."""
        whitespace_names = [
            "   ",
            "\t\t",
            "\n\n",
            "   \t\n   "
        ]

        for name in whitespace_names:
            with pytest.raises(EntityNameValidationError) as exc_info:
                validate_entity_name(name)
            assert "cannot be empty" in str(exc_info.value).lower()

    def test_none_entity_rejected(self):
        """Test that None entity names are rejected."""
        with pytest.raises(EntityNameValidationError) as exc_info:
            validate_entity_name(None)

        error_msg = str(exc_info.value)
        assert "cannot be none" in error_msg.lower()
        assert "example" in error_msg.lower()

    def test_forward_slash_rejected(self):
        """Test that forward slashes are rejected (path traversal prevention)."""
        invalid_names = [
            "path/to/class",
            "my/function",
            "/absolute/path",
            "a/b/c",
            "Class/method"
        ]

        for name in invalid_names:
            with pytest.raises(EntityNameValidationError) as exc_info:
                validate_entity_name(name)

            error_msg = str(exc_info.value)
            assert "forbidden characters" in error_msg.lower()
            assert "forward slash" in error_msg.lower()

    def test_backslash_rejected(self):
        """Test that backslashes are rejected (path traversal prevention)."""
        invalid_names = [
            "path\\to\\class",
            "my\\function",
            "\\absolute\\path",
            "a\\b\\c",
            "Class\\method"
        ]

        for name in invalid_names:
            with pytest.raises(EntityNameValidationError) as exc_info:
                validate_entity_name(name)

            error_msg = str(exc_info.value)
            assert "forbidden characters" in error_msg.lower()
            assert "backslash" in error_msg.lower()

    def test_null_byte_rejected(self):
        """Test that null bytes are rejected (string truncation attack prevention)."""
        invalid_names = [
            "class\x00name",
            "\x00start",
            "end\x00"
        ]

        for name in invalid_names:
            with pytest.raises(EntityNameValidationError) as exc_info:
                validate_entity_name(name)

            error_msg = str(exc_info.value)
            assert "forbidden characters" in error_msg.lower()
            assert "null byte" in error_msg.lower()

    def test_long_entity_rejected(self):
        """Test that entity names exceeding MAX_ENTITY_NAME_LENGTH are rejected."""
        long_name = "x" * (MAX_ENTITY_NAME_LENGTH + 1)

        with pytest.raises(EntityNameValidationError) as exc_info:
            validate_entity_name(long_name)

        error_msg = str(exc_info.value)
        assert "exceeds maximum length" in error_msg.lower()
        assert str(MAX_ENTITY_NAME_LENGTH) in error_msg

    def test_exact_max_length_accepted(self):
        """Test that entity names at exactly MAX_ENTITY_NAME_LENGTH are accepted."""
        exact_name = "x" * MAX_ENTITY_NAME_LENGTH

        result = validate_entity_name(exact_name)

        assert result == exact_name
        assert len(result) == MAX_ENTITY_NAME_LENGTH

    def test_one_less_than_max_accepted(self):
        """Test that entity names one less than MAX_ENTITY_NAME_LENGTH are accepted."""
        name = "x" * (MAX_ENTITY_NAME_LENGTH - 1)

        result = validate_entity_name(name)

        assert result == name

    def test_custom_max_length(self):
        """Test that custom max_length is respected."""
        custom_max = 50
        long_name = "x" * 60

        with pytest.raises(EntityNameValidationError) as exc_info:
            validate_entity_name(long_name, max_length=custom_max)

        error_msg = str(exc_info.value)
        assert "50" in error_msg  # Custom max should be in error

    def test_custom_field_name_in_error(self):
        """Test that custom field_name appears in error messages."""
        with pytest.raises(EntityNameValidationError) as exc_info:
            validate_entity_name("", field_name="class_name")

        error_msg = str(exc_info.value)
        assert "class_name" in error_msg.lower()

    def test_entity_stripped_of_whitespace(self):
        """Test that leading/trailing whitespace is stripped."""
        name_with_whitespace = "   MyClass   "

        result = validate_entity_name(name_with_whitespace)

        assert result == "MyClass"
        assert result == name_with_whitespace.strip()

    def test_single_character_entity_accepted(self):
        """Test that single character entity names are accepted."""
        single_char = "a"

        result = validate_entity_name(single_char)

        assert result == single_char

    def test_unicode_entity_accepted(self):
        """Test that unicode entity names are handled correctly."""
        unicode_names = [
            "类名",  # Chinese
            "Κλάση",  # Greek
            "クラス",  # Japanese
        ]

        for name in unicode_names:
            result = validate_entity_name(name)
            assert result == name

    def test_error_message_includes_examples(self):
        """Test that error messages include helpful examples."""
        with pytest.raises(EntityNameValidationError) as exc_info:
            validate_entity_name("")

        error_msg = str(exc_info.value)
        # Should include examples
        assert "config" in error_msg.lower() or "process_data" in error_msg.lower()

    def test_error_suggests_search_for_path(self):
        """Test that error for path separators suggests using search_knowledge."""
        with pytest.raises(EntityNameValidationError) as exc_info:
            validate_entity_name("path/to/file")

        error_msg = str(exc_info.value)
        assert "search_knowledge" in error_msg

    def test_special_characters_allowed(self):
        """Test that special characters other than forbidden are allowed."""
        # Python allows these in identifiers/strings
        allowed_names = [
            "class_with-hyphen",
            "class.method",  # Dots are allowed (for qualified names)
            "func@decorator",  # Not common but not forbidden
            "data$var",
            "name#tag"
        ]

        for name in allowed_names:
            result = validate_entity_name(name)
            assert result == name

    def test_multiple_forbidden_chars_all_reported(self):
        """Test that when multiple forbidden chars present, all are reported."""
        # Contains both / and \
        with pytest.raises(EntityNameValidationError) as exc_info:
            validate_entity_name("a/b\\c")

        error_msg = str(exc_info.value)
        assert "forward slash" in error_msg.lower()
        assert "backslash" in error_msg.lower()


class TestColumnNameValidation:
    """Test column name validation for SQL injection prevention (SEC-006)."""

    def test_valid_simple_column_names(self):
        """Test that valid simple column names are accepted."""
        valid_names = [
            "id",
            "file_path",
            "created_at",
            "content",
            "vector",
            "_internal",
            "__double_underscore",
            "Column123",
            "a",
            "A_b_C_123",
        ]

        for name in valid_names:
            result = validate_column_name(name)
            assert result == name

    def test_valid_nested_column_names(self):
        """Test that valid nested (dotted) column names are accepted."""
        valid_names = [
            "metadata.type",
            "user.profile.name",
            "a.b.c.d",
            "Config.settings",
            "_internal._field",
        ]

        for name in valid_names:
            result = validate_column_name(name, allow_nested=True)
            assert result == name

    def test_nested_rejected_when_disabled(self):
        """Test that nested column names are rejected when allow_nested=False."""
        with pytest.raises(ColumnNameValidationError) as exc_info:
            validate_column_name("metadata.type", allow_nested=False)

        error_msg = str(exc_info.value)
        assert "dots" in error_msg.lower() or "nested" in error_msg.lower()

    def test_empty_column_rejected(self):
        """Test that empty column names are rejected."""
        with pytest.raises(ColumnNameValidationError) as exc_info:
            validate_column_name("")

        error_msg = str(exc_info.value)
        assert "cannot be empty" in error_msg.lower()

    def test_none_column_rejected(self):
        """Test that None column names are rejected."""
        with pytest.raises(ColumnNameValidationError) as exc_info:
            validate_column_name(None)

        error_msg = str(exc_info.value)
        assert "cannot be none" in error_msg.lower()

    def test_sql_injection_patterns_rejected(self):
        """Test that SQL injection patterns are rejected."""
        malicious_names = [
            "column'; DROP TABLE--",
            "column OR 1=1--",
            "column; DELETE FROM users",
            "column UNION SELECT * FROM passwords",
            "'OR''='",
            "1; DROP TABLE document_chunks;--",
            "column/*comment*/name",
        ]

        for name in malicious_names:
            with pytest.raises(ColumnNameValidationError):
                validate_column_name(name)

    def test_invalid_starting_characters(self):
        """Test that columns starting with numbers are rejected."""
        invalid_names = [
            "123column",
            "1_name",
            "9abc",
        ]

        for name in invalid_names:
            with pytest.raises(ColumnNameValidationError) as exc_info:
                validate_column_name(name)

            error_msg = str(exc_info.value)
            assert "start with" in error_msg.lower() or "pattern" in error_msg.lower()

    def test_special_characters_rejected(self):
        """Test that special characters are rejected."""
        invalid_names = [
            "column-name",  # hyphen
            "column name",  # space
            "column@field",  # at sign
            "column#field",  # hash
            "column$field",  # dollar
            "column%field",  # percent
            "column!field",  # exclamation
            "column*field",  # asterisk
        ]

        for name in invalid_names:
            with pytest.raises(ColumnNameValidationError):
                validate_column_name(name)

    def test_invalid_dot_patterns(self):
        """Test that invalid dot patterns are rejected."""
        invalid_patterns = [
            ".column",      # starts with dot
            "column.",      # ends with dot
            "column..field",  # consecutive dots
            "..column",     # multiple leading dots
            "column..",     # multiple trailing dots
            "a..b.c",       # embedded consecutive dots
        ]

        for pattern in invalid_patterns:
            with pytest.raises(ColumnNameValidationError) as exc_info:
                validate_column_name(pattern, allow_nested=True)

            error_msg = str(exc_info.value)
            assert "dot" in error_msg.lower() or "empty" in error_msg.lower()

    def test_long_column_name_rejected(self):
        """Test that very long column names are rejected (DoS prevention)."""
        long_name = "x" * 129  # Exceeds 128 char limit

        with pytest.raises(ColumnNameValidationError) as exc_info:
            validate_column_name(long_name)

        error_msg = str(exc_info.value)
        assert "exceeds maximum length" in error_msg.lower() or "128" in error_msg

    def test_exact_max_length_accepted(self):
        """Test that columns at exactly max length (128) are accepted."""
        exact_name = "x" * 128

        result = validate_column_name(exact_name)

        assert result == exact_name
        assert len(result) == 128

    def test_whitespace_stripped(self):
        """Test that leading/trailing whitespace is stripped."""
        name_with_whitespace = "   column_name   "

        result = validate_column_name(name_with_whitespace)

        assert result == "column_name"

    def test_custom_field_name_in_error(self):
        """Test that custom field_name appears in error messages."""
        with pytest.raises(ColumnNameValidationError) as exc_info:
            validate_column_name("", field_name="order_by")

        error_msg = str(exc_info.value)
        assert "order_by" in error_msg.lower()


class TestColumnNamesValidation:
    """Test column names list validation (SEC-006)."""

    def test_valid_column_list(self):
        """Test that valid column name lists are accepted."""
        valid_lists = [
            ["id", "name", "created_at"],
            ["file_path", "content", "vector"],
            ["a", "b", "c"],
        ]

        for cols in valid_lists:
            result = validate_column_names(cols)
            assert result == cols

    def test_empty_list_rejected(self):
        """Test that empty column lists are handled properly (not rejected)."""
        # Note: Empty list is valid (no columns to validate)
        result = validate_column_names([])
        assert result == []

    def test_none_list_rejected(self):
        """Test that None list is rejected."""
        with pytest.raises(ColumnNameValidationError) as exc_info:
            validate_column_names(None)

        error_msg = str(exc_info.value)
        assert "cannot be none" in error_msg.lower()

    def test_invalid_type_rejected(self):
        """Test that non-list types are rejected."""
        with pytest.raises(ColumnNameValidationError) as exc_info:
            validate_column_names("not_a_list")

        error_msg = str(exc_info.value)
        assert "must be a list" in error_msg.lower()

    def test_invalid_column_in_list_rejected(self):
        """Test that lists with invalid columns are rejected."""
        with pytest.raises(ColumnNameValidationError) as exc_info:
            validate_column_names(["id", "valid_column", "invalid-column"])

        error_msg = str(exc_info.value)
        # Should include index information
        assert "2" in error_msg or "invalid-column" in error_msg

    def test_sql_injection_in_list_rejected(self):
        """Test that SQL injection in column list is rejected."""
        with pytest.raises(ColumnNameValidationError):
            validate_column_names(["id", "'; DROP TABLE--"])


class TestTableNameValidation:
    """Test table name validation for SQL injection prevention (SEC-006)."""

    def test_known_tables_accepted(self):
        """Test that known table names are accepted."""
        for table in KNOWN_TABLE_NAMES:
            result = validate_table_name(table)
            assert result == table

    def test_unknown_table_rejected_by_default(self):
        """Test that unknown table names are rejected by default."""
        with pytest.raises(ColumnNameValidationError) as exc_info:
            validate_table_name("unknown_table")

        error_msg = str(exc_info.value)
        assert "unknown table" in error_msg.lower()
        # Should list valid tables
        assert "document_chunks" in error_msg

    def test_unknown_table_accepted_with_flag(self):
        """Test that unknown tables are accepted when allow_unknown=True."""
        # Valid pattern but not in allowlist
        result = validate_table_name("custom_table_name", allow_unknown=True)
        assert result == "custom_table_name"

    def test_sql_injection_rejected_even_with_allow_unknown(self):
        """Test that SQL injection is rejected even with allow_unknown=True."""
        malicious_names = [
            "table; DROP TABLE--",
            "users'; DELETE FROM users--",
            "table OR 1=1",
        ]

        for name in malicious_names:
            with pytest.raises(ColumnNameValidationError):
                validate_table_name(name, allow_unknown=True)

    def test_nested_table_names_rejected(self):
        """Test that table names cannot contain dots."""
        with pytest.raises(ColumnNameValidationError):
            validate_table_name("schema.table", allow_unknown=True)

    def test_known_table_names_list(self):
        """Test that KNOWN_TABLE_NAMES contains expected tables."""
        expected_tables = {
            "document_chunks",
            "graph_entities",
            "graph_relationships",
            "memory_episodic",
            "mcp_sessions",
        }

        assert expected_tables.issubset(KNOWN_TABLE_NAMES)


class TestQuerySpecColumnValidation:
    """Test QuerySpec integration with column validation (SEC-006)."""

    def test_queryspec_validates_table_name(self):
        """Test that QuerySpec validates table names."""
        from agent_vault.database.query_spec import QuerySpec

        # Valid table name should work
        spec = QuerySpec(table="document_chunks")
        assert spec.table == "document_chunks"

    def test_queryspec_validates_vector_column(self):
        """Test that QuerySpec validates vector_column."""
        from agent_vault.database.query_spec import QuerySpec

        # Valid vector column should work
        spec = QuerySpec(table="document_chunks", vector_column="vector")
        assert spec.vector_column == "vector"

        # Invalid vector column should fail
        with pytest.raises(ValueError) as exc_info:
            QuerySpec(table="document_chunks", vector_column="vector'; DROP TABLE--")

        assert "vector_column" in str(exc_info.value).lower()

    def test_queryspec_validates_order_by(self):
        """Test that QuerySpec validates order_by column."""
        from agent_vault.database.query_spec import QuerySpec

        # Valid order_by should work
        spec = QuerySpec(table="document_chunks", order_by="created_at")
        assert spec.order_by == "created_at"

        # Invalid order_by should fail
        with pytest.raises(ValueError) as exc_info:
            QuerySpec(table="document_chunks", order_by="created_at; DROP TABLE--")

        assert "order_by" in str(exc_info.value).lower()

    def test_queryspec_validates_fts_columns(self):
        """Test that QuerySpec validates fts_columns."""
        from agent_vault.database.query_spec import QuerySpec

        # Valid fts_columns should work
        spec = QuerySpec(table="document_chunks", fts_columns=["content", "title"])
        assert spec.fts_columns == ["content", "title"]

        # Invalid fts_columns should fail
        with pytest.raises(ValueError) as exc_info:
            QuerySpec(table="document_chunks", fts_columns=["content", "'; DROP--"])

        assert "fts_columns" in str(exc_info.value).lower()

    def test_queryspec_validates_select_columns(self):
        """Test that QuerySpec validates select_columns."""
        from agent_vault.database.query_spec import QuerySpec

        # Valid select_columns should work (must include 'id')
        spec = QuerySpec(table="document_chunks", select_columns=["id", "content"])
        assert spec.select_columns == ["id", "content"]

        # Invalid select_columns should fail
        with pytest.raises(ValueError) as exc_info:
            QuerySpec(table="document_chunks", select_columns=["id", "'; DROP TABLE--"])

        assert "select_columns" in str(exc_info.value).lower()

    def test_queryspec_allows_nested_in_select(self):
        """Test that QuerySpec allows nested columns in select_columns."""
        from agent_vault.database.query_spec import QuerySpec

        # Nested fields should work in select_columns
        spec = QuerySpec(
            table="document_chunks",
            select_columns=["id", "metadata.type"]
        )
        assert spec.select_columns == ["id", "metadata.type"]
