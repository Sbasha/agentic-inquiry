"""Utilities to execute parser implementations and normalize their outputs.

This module introduces a lightweight parser protocol along with helpers for
executing individual parsers or batches of parsers.  Outputs are normalised
into the shared :class:`~agentic_inquiry.parsers.models.ParsedDocument` and
:class:`~agentic_inquiry.parsers.models.ParserChunk` data classes so downstream
consumers can operate on a consistent structure regardless of the underlying
parser implementation.

The module also exposes a small registry that enables applications to register
parser implementations once and fetch them later by name.  This removes the
need for boilerplate factories in downstream projects.

Parser Protocol
---------------
The ParserProtocol requires a parse(path: str) method. Parsers may optionally
implement a can_parse(path: str) -> bool method for efficient parser selection.
If can_parse is not implemented, the parser is assumed to handle all files.

The can_parse method should perform only lightweight checks (file extension,
MIME type) and should NOT read file content for performance reasons.
"""

from __future__ import annotations

from pathlib import Path
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Tuple,
    Union,
    runtime_checkable,
)

from .models import ParsedDocument, ParserChunk


ParsedDocumentLike = Union[
    ParsedDocument,
    Mapping[str, Any],
    Iterable[ParserChunk],
    None,
]


@runtime_checkable
class ParserProtocol(Protocol):
    """Minimal protocol that parser implementations are expected to satisfy.
    
    The protocol requires an async parse method. The can_parse method is optional
    and can be used for efficient parser selection in parser chains.
    All methods are async to support non-blocking I/O operations.
    """

    async def parse(self, path: str) -> ParsedDocumentLike:
        """Parse the document at ``path`` asynchronously and return structured data.
        
        Args:
            path: Path to the document to parse
            
        Returns:
            Parsed document data structure
            
        Raises:
            ParserError: If parsing fails
        """
        ...


# ParserCallable can be either sync or async
ParserCallable = Callable[[str], Union[ParsedDocumentLike, Coroutine[Any, Any, ParsedDocumentLike]]]


def _default_doc_id(file_path: str) -> str:
    path = Path(file_path)
    return path.name or str(path)


def normalize_chunk(data: Any) -> ParserChunk:
    """Coerce ``data`` into a :class:`ParserChunk` instance."""

    if isinstance(data, ParserChunk):
        return data

    if isinstance(data, Mapping):
        mapping = dict(data)
        return ParserChunk(
            content=mapping.get("content"),
            fts_text=mapping.get("fts_text"),
            content_type=mapping.get("content_type"),
            language=mapping.get("language"),
            page_number=mapping.get("page_number"),
            line_start=mapping.get("line_start"),
            line_end=mapping.get("line_end"),
            element_type=mapping.get("element_type"),
            element_name=mapping.get("element_name"),
            parent_id=mapping.get("parent_id"),
            child_ids=mapping.get("child_ids") or [],
            symbols=mapping.get("symbols", mapping.get("code_symbols", [])),
            relationships=mapping.get("relationships", []),
            metadata=mapping.get("metadata"),
            ranking_signals=mapping.get("ranking_signals"),
            symbol_rankings=mapping.get("symbol_rankings", {}),
            symbol_metadata=mapping.get("symbol_metadata", {}),
        )

    raise TypeError(
        "Parser outputs must be ParserChunk instances or mappings that can "
        "be converted into ParserChunk. Received %r" % (data,)
    )


def _normalize_chunk_iterable(chunks: Optional[Iterable[Any]]) -> List[ParserChunk]:
    if chunks is None:
        return []
    return [normalize_chunk(chunk) for chunk in chunks]


def normalize_document(
    data: ParsedDocumentLike,
    *,
    doc_id: Optional[str],
    file_path: str,
) -> ParsedDocument:
    """Convert parser output into a :class:`ParsedDocument` instance."""

    resolved_doc_id = doc_id or _default_doc_id(file_path)

    if isinstance(data, ParsedDocument):
        return data

    if data is None:
        return ParsedDocument(doc_id=resolved_doc_id, file_path=file_path, chunks=[])

    if isinstance(data, Mapping):
        mapping: MutableMapping[str, Any] = dict(data)

        mapped_doc_id = mapping.get("doc_id", resolved_doc_id)
        mapped_file_path = mapping.get("file_path", file_path)

        chunks_value = mapping.get("chunks")
        normalized_chunks = _normalize_chunk_iterable(chunks_value)
        return ParsedDocument(
            doc_id=mapped_doc_id,
            file_path=mapped_file_path,
            chunks=normalized_chunks,
        )

    if isinstance(data, Iterable):
        return ParsedDocument(
            doc_id=resolved_doc_id,
            file_path=file_path,
            chunks=_normalize_chunk_iterable(data),
        )

    raise TypeError(
        "Parser outputs must resolve to ParsedDocument, Iterable[ParserChunk], "
        "or a mapping providing the ParsedDocument fields. Received %r" % (data,)
    )


async def execute_parser(
    parser: Union[ParserCallable, ParserProtocol],
    path: str,
    *,
    doc_id: Optional[str] = None,
    **kwargs: Any,
) -> ParsedDocument:
    """Execute ``parser`` against ``path`` and normalise the output.
    
    Args:
        parser: Parser instance or callable
        path: Path to file to parse
        doc_id: Optional document ID
        **kwargs: Additional parameters to pass to parser (e.g., db_manager, embedding_service, project_id)
    
    Returns:
        Normalized ParsedDocument
    """
    import asyncio

    if isinstance(parser, ParserProtocol):
        # Pass kwargs to parser if it supports them
        raw = await parser.parse(path, **kwargs)
    else:
        result = parser(path)
        # Handle both sync and async callables
        if asyncio.iscoroutine(result):
            raw = await result
        else:
            raw = result
    return normalize_document(raw, doc_id=doc_id, file_path=path)


async def execute_parsers(
    parsers: Iterable[Union[ParserCallable, ParserProtocol]],
    path: str,
    *,
    doc_id: Optional[str] = None,
) -> List[ParsedDocument]:
    """Execute multiple parsers and return their parsed documents."""

    documents: List[ParsedDocument] = []
    for index, parser in enumerate(parsers):
        combined_doc_id = doc_id
        if combined_doc_id and index:
            combined_doc_id = f"{combined_doc_id}:{index}"
        documents.append(await execute_parser(parser, path, doc_id=combined_doc_id))
    return documents


class ParserRegistry:
    """Registry for parser callables keyed by arbitrary names."""

    def __init__(self) -> None:
        self._parsers: Dict[str, ParserCallable] = {}
        self._parser_instances: Dict[str, Union[ParserCallable, ParserProtocol]] = {}

    def register(
        self,
        name: str,
        parser: Union[ParserCallable, ParserProtocol],
        *,
        overwrite: bool = False,
    ) -> None:
        if name in self._parsers and not overwrite:
            raise ValueError(f"Parser '{name}' is already registered")
        # Store the full parser instance for access to can_parse
        self._parser_instances[name] = parser
        # Store the callable for backward compatibility
        if isinstance(parser, ParserProtocol):
            self._parsers[name] = parser.parse
        else:
            self._parsers[name] = parser

    def unregister(self, name: str) -> None:
        self._parsers.pop(name, None)
        self._parser_instances.pop(name, None)

    def get(self, name: str) -> ParserCallable:
        try:
            return self._parsers[name]
        except KeyError as exc:
            raise KeyError(f"Parser '{name}' is not registered") from exc

    def get_instance(self, name: str) -> Union[ParserCallable, ParserProtocol]:
        """Get the full parser instance (not just the callable).
        
        This is useful for accessing additional methods like can_parse.
        """
        try:
            return self._parser_instances[name]
        except KeyError as exc:
            raise KeyError(f"Parser '{name}' is not registered") from exc

    def available(self) -> Tuple[str, ...]:
        return tuple(sorted(self._parsers))

    async def parse(self, name: str, path: str, *, doc_id: Optional[str] = None) -> ParsedDocument:
        parser = self.get(name)
        return await execute_parser(parser, path, doc_id=doc_id)


_registry = ParserRegistry()


def register_parser(
    name: str,
    parser: Union[ParserCallable, ParserProtocol],
    *,
    overwrite: bool = False,
) -> None:
    """Register ``parser`` globally under ``name``."""

    _registry.register(name, parser, overwrite=overwrite)


def unregister_parser(name: str) -> None:
    """Remove ``name`` from the global parser registry if present."""

    _registry.unregister(name)


def get_parser(name: str) -> ParserCallable:
    """Retrieve a parser callable registered under ``name``."""

    return _registry.get(name)


def get_parser_instance(name: str) -> Union[ParserCallable, ParserProtocol]:
    """Retrieve the full parser instance registered under ``name``.
    
    This returns the full parser object, not just the parse method,
    allowing access to additional methods like can_parse.
    """

    return _registry.get_instance(name)


async def parse_with_registry(
    name: str,
    path: str,
    *,
    doc_id: Optional[str] = None,
) -> ParsedDocument:
    """Convenience wrapper around :class:`ParserRegistry.parse`."""

    return await _registry.parse(name, path, doc_id=doc_id)


def available_parsers() -> Tuple[str, ...]:
    """Return the tuple of globally registered parser names."""

    return _registry.available()


__all__ = [
    "ParserProtocol",
    "ParserCallable",
    "ParsedDocumentLike",
    "normalize_chunk",
    "normalize_document",
    "execute_parser",
    "execute_parsers",
    "ParserRegistry",
    "register_parser",
    "unregister_parser",
    "get_parser",
    "get_parser_instance",
    "parse_with_registry",
    "available_parsers",
]

