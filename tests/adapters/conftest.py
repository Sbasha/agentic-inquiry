"""Fixtures for adapter tests.

Adapter tests verify assumptions about third-party libraries.
These tests ensure that library behavior matches our expectations
and catch breaking changes in dependencies early.
"""

from __future__ import annotations

import importlib.util
import pytest


@pytest.fixture(scope="session")
def skip_if_no_sentence_transformers():
    """Skip test if sentence-transformers not installed.

    Uses importlib.util.find_spec for fast check without actually
    importing (which triggers slow transformers module scan).
    """
    if importlib.util.find_spec("sentence_transformers") is None:
        pytest.skip("sentence-transformers not installed")


@pytest.fixture(scope="session")
def skip_if_no_tree_sitter():
    """Skip test if tree-sitter or Python grammar not installed.

    Uses importlib.util.find_spec for fast availability check.
    """
    if importlib.util.find_spec("tree_sitter") is None:
        pytest.skip("tree-sitter not installed")
    if importlib.util.find_spec("tree_sitter_python") is None:
        pytest.skip("tree_sitter_python not installed")


@pytest.fixture(scope="session")
def skip_if_no_lancedb():
    """Skip test if lancedb not installed.

    Uses importlib.util.find_spec for fast availability check.
    """
    if importlib.util.find_spec("lancedb") is None:
        pytest.skip("lancedb not installed")
