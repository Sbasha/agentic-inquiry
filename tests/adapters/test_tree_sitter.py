"""Tests for tree-sitter library assumptions.

These tests verify that tree-sitter parsing behaves as expected
and that our assumptions about AST structure are correct.

Run with: pytest tests/adapters/test_tree_sitter.py -v
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.adapters]


class TestPythonParsing:
    """Test Python parsing assumptions."""

    def test_function_node_type(self, skip_if_no_tree_sitter):
        """Python functions have expected node type."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        code = b"def hello():\n    pass"
        tree = parser.parse(code)

        # Find function definition
        root = tree.root_node
        func_node = root.children[0]

        assert func_node.type == "function_definition"

    def test_class_node_type(self, skip_if_no_tree_sitter):
        """Python classes have expected node type."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        code = b"class Foo:\n    pass"
        tree = parser.parse(code)

        root = tree.root_node
        class_node = root.children[0]

        assert class_node.type == "class_definition"

    def test_async_function_node_type(self, skip_if_no_tree_sitter):
        """Async functions have expected node type."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        code = b"async def hello():\n    pass"
        tree = parser.parse(code)

        root = tree.root_node
        func_node = root.children[0]

        assert func_node.type == "function_definition"

    def test_decorated_function(self, skip_if_no_tree_sitter):
        """Decorated functions are wrapped in decorated_definition."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        code = b"@decorator\ndef hello():\n    pass"
        tree = parser.parse(code)

        root = tree.root_node
        decorated = root.children[0]

        assert decorated.type == "decorated_definition"

        # Function should be inside
        func_node = decorated.child_by_field_name("definition")
        assert func_node.type == "function_definition"


class TestNodeNavigation:
    """Test AST navigation assumptions."""

    def test_children_traversal(self, skip_if_no_tree_sitter):
        """Children can be traversed correctly."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        code = b"def foo():\n    x = 1\n    y = 2"
        tree = parser.parse(code)

        func = tree.root_node.children[0]
        body = func.child_by_field_name("body")

        # Block should have children
        assert body.type == "block"
        assert body.child_count >= 2

    def test_named_children_filter(self, skip_if_no_tree_sitter):
        """Named children excludes punctuation nodes."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        code = b"[1, 2, 3]"
        tree = parser.parse(code)

        expr = tree.root_node.children[0]
        list_node = expr.children[0]

        # All children includes brackets and commas
        all_children = list(list_node.children)

        # Named children should only include integers
        named_children = list(list_node.named_children)

        assert len(named_children) < len(all_children)
        assert all(c.type == "integer" for c in named_children)

    def test_text_extraction(self, skip_if_no_tree_sitter):
        """Node text can be extracted from source."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        code = b"def hello_world():\n    pass"
        tree = parser.parse(code)

        func = tree.root_node.children[0]
        name_node = func.child_by_field_name("name")

        # Extract text using byte range
        name_text = code[name_node.start_byte:name_node.end_byte].decode()
        assert name_text == "hello_world"


class TestErrorHandling:
    """Test error handling assumptions."""

    def test_syntax_error_produces_error_node(self, skip_if_no_tree_sitter):
        """Syntax errors produce ERROR nodes."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        code = b"def broken(\n    "
        tree = parser.parse(code)

        # Tree should have error node
        assert tree.root_node.has_error

    def test_partial_parse_recovers(self, skip_if_no_tree_sitter):
        """Parser recovers after syntax errors."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        code = b"def broken(\n    \ndef good():\n    pass"
        tree = parser.parse(code)

        # Should still parse valid parts
        root = tree.root_node
        assert root.child_count >= 2  # Both definitions attempted

    def test_empty_input(self, skip_if_no_tree_sitter):
        """Empty input produces empty tree."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        tree = parser.parse(b"")
        assert tree.root_node.type == "module"
        assert tree.root_node.child_count == 0


class TestPositionTracking:
    """Test position tracking assumptions."""

    def test_line_numbers_zero_indexed(self, skip_if_no_tree_sitter):
        """Line numbers are 0-indexed."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        code = b"x = 1\ny = 2\nz = 3"
        tree = parser.parse(code)

        # First statement on line 0
        first = tree.root_node.children[0]
        assert first.start_point[0] == 0

        # Third statement on line 2
        third = tree.root_node.children[2]
        assert third.start_point[0] == 2

    def test_column_tracking(self, skip_if_no_tree_sitter):
        """Column positions are tracked correctly."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        code = b"    x = 1"  # 4 space indent
        tree = parser.parse(code)

        expr = tree.root_node.children[0]
        assert expr.start_point[1] == 4  # Column 4

    def test_byte_positions(self, skip_if_no_tree_sitter):
        """Byte positions match source bytes."""
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser

        parser = Parser(Language(tspython.language()))

        code = b"variable = 123"
        tree = parser.parse(code)

        expr = tree.root_node.children[0]
        assign = expr.children[0]
        target = assign.child_by_field_name("left")

        extracted = code[target.start_byte:target.end_byte]
        assert extracted == b"variable"
