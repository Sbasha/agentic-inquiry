"""Parser utilities exposed for downstream consumers.

The :mod:`agentic_inquiry.parsers` package exposes a small set of helpers that
standardise how parser implementations communicate with the rest of the
library.  Downstream projects can register their own parser implementations or
re-use the built-in registry helpers without re-implementing boilerplate.

Example usage::

    from agentic_inquiry.parsers import ParserRegistry, register_parser, parse_with_registry

    class MyParser:
        def parse(self, path: str):
            ...  # return a ParsedDocument or compatible structure

    register_parser("my_parser", MyParser())
    document = parse_with_registry("my_parser", "/path/to/file.py")

"""

from .chain import ParserChain, ParsingError, create_parser_chain
from .executor import (
    ParserCallable,
    ParserProtocol,
    ParsedDocumentLike,
    ParserRegistry,
    available_parsers,
    execute_parser,
    execute_parsers,
    get_parser,
    normalize_chunk,
    normalize_document,
    parse_with_registry,
    register_parser,
    unregister_parser,
)
from .models import ParsedDocument, ParserChunk
from .validators import (
    ChunkValidationIssue,
    assert_valid_chunks,
    assert_valid_parsed_document,
    validate_chunks_have_text,
    validate_parsed_document,
)

__all__ = [
    # High-level API
    "ParserChain",
    "ParsingError",
    "create_parser_chain",
    # Core types
    "ParserCallable",
    "ParserProtocol",
    "ParsedDocumentLike",
    "ParserRegistry",
    "ParsedDocument",
    "ParserChunk",
    # Registry functions
    "available_parsers",
    "execute_parser",
    "execute_parsers",
    "get_parser",
    "normalize_chunk",
    "normalize_document",
    "parse_with_registry",
    "register_parser",
    "unregister_parser",
    # Validation
    "ChunkValidationIssue",
    "assert_valid_chunks",
    "assert_valid_parsed_document",
    "validate_chunks_have_text",
    "validate_parsed_document",
]

