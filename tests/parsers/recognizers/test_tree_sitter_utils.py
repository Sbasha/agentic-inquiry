"""Tests for the shared tree-sitter helpers.

These helpers are the seam that the second recognizer will reuse.
Pinning the contract here means a future refactor can't quietly break
the pattern without a failing test — even before that second
recognizer exists.
"""

from __future__ import annotations

import pytest

from agentic_inquiry.parsers.recognizers._tree_sitter_utils import (
    first_child_of_type,
    identifier_text,
    iter_children_of_type,
    last_name_segment,
    node_text,
)

pytestmark = pytest.mark.unit


def _java_tree(source: str):
    """Parse ``source`` as Java and return the root node + source bytes.

    Uses the same tree-sitter pack the recognizers do. Skips the test
    if the grammar isn't available — the helpers themselves don't
    need Java at all, but they're easier to exercise with a real AST
    than by hand-crafting mock nodes.
    """
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:  # pragma: no cover
        pytest.skip("tree_sitter_language_pack not installed")
    parser = get_parser("java")
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    return tree.root_node, source_bytes


class TestLastNameSegment:
    def test_bare_name_returned_as_is(self):
        assert last_name_segment("GetMapping") == "GetMapping"

    def test_qualified_name_returns_tail(self):
        assert (
            last_name_segment("org.springframework.web.bind.annotation.GetMapping")
            == "GetMapping"
        )

    def test_empty_returns_empty(self):
        assert last_name_segment("") == ""

    def test_single_dot(self):
        assert last_name_segment("a.b") == "b"


class TestASTHelpers:
    def test_iter_children_of_type_filters_by_type(self):
        root, _ = _java_tree("class A {} class B {} interface C {}")
        class_nodes = list(iter_children_of_type(root, "class_declaration"))
        interface_nodes = list(iter_children_of_type(root, "interface_declaration"))
        assert len(class_nodes) == 2
        assert len(interface_nodes) == 1

    def test_first_child_of_type_returns_none_when_absent(self):
        root, _ = _java_tree("class A {}")
        assert first_child_of_type(root, "interface_declaration") is None

    def test_first_child_of_type_returns_first_match(self):
        root, _ = _java_tree("class A {} class B {}")
        first = first_child_of_type(root, "class_declaration")
        assert first is not None
        assert first.type == "class_declaration"

    def test_node_text_decodes_span(self):
        root, source = _java_tree("class Alpha {}")
        class_node = first_child_of_type(root, "class_declaration")
        text = node_text(class_node, source)
        assert text == "class Alpha {}"

    def test_identifier_text_returns_field_value(self):
        root, source = _java_tree("class Alpha {}")
        class_node = first_child_of_type(root, "class_declaration")
        assert identifier_text(class_node, "name", source) == "Alpha"

    def test_identifier_text_returns_empty_when_field_missing(self):
        root, source = _java_tree("class Alpha {}")
        class_node = first_child_of_type(root, "class_declaration")
        # ``body`` exists; ``nonexistent_field`` does not.
        assert identifier_text(class_node, "nonexistent_field", source) == ""
