"""Shared utilities for parser implementations.

This module contains utilities used by multiple parser implementations,
such as tree-sitter integration, language detection, and chunking logic.

Copied from akb_iq and adapted for the new parser registry system.
"""

from .languages import (
    LanguageRegistry,
    get_language_registry,
    detect_language,
)
from .tree_sitter import (
    TreeSitterNode,
    TreeSitterParser,
    FUNCTION_QUERY_TEMPLATES,
    CLASS_QUERY_TEMPLATES,
    IMPORT_QUERY_TEMPLATES,
)
from .query_loader import (
    QueryLoader,
    get_query_loader,
    load_query,
)
from .chunking import (
    chunk_text_by_tokens,
    chunk_text_by_lines,
    merge_small_chunks,
)

__all__ = [
    # Languages
    'LanguageRegistry',
    'get_language_registry',
    'detect_language',
    # Tree-sitter
    'TreeSitterNode',
    'TreeSitterParser',
    'FUNCTION_QUERY_TEMPLATES',
    'CLASS_QUERY_TEMPLATES',
    'IMPORT_QUERY_TEMPLATES',
    # Query loader
    'QueryLoader',
    'get_query_loader',
    'load_query',
    # Chunking
    'chunk_text_by_tokens',
    'chunk_text_by_lines',
    'merge_small_chunks',
]
