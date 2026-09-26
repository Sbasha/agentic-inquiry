"""Partition parsed code into retrieval chunks that follow definition boundaries.

The code parser groups definitions for the knowledge graph: its chunks overlap
(a class chunk spans every method chunk inside it), can be a whole class of any
size, and may add a whole-file chunk. Those shapes serve graph extraction and
framework recognizers, not retrieval. This step runs after both and replaces
the chunks with a partition of the file: every line belongs to exactly one
chunk, a chunk holds at most ``max_chars`` characters unless one line is
longer, and breaks fall on definition boundaries (functions, methods,
classes). The graph data on the parser's chunks (symbols, symbol metadata,
relationships, rankings) moves onto the partition chunk that contains the
original chunk's first line, so the graph built from the document is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from agentic_inquiry.parsers.implementations.utils.chunking import pack_lines
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk

CHUNKER_VERSION = "definition-partition-v1"


@dataclass
class _Definition:
    start: int
    end: int
    name: str
    kind: str
    children: List["_Definition"] = field(default_factory=list)


def _definitions(chunks: Sequence[ParserChunk], line_count: int) -> List[_Definition]:
    """Nested definitions from the parser's symbol metadata; partial overlaps are dropped."""
    seen: Dict[Tuple[int, int], _Definition] = {}
    for chunk in chunks:
        for name, meta in (chunk.symbol_metadata or {}).items():
            start, end = meta.get("start_line"), meta.get("end_line")
            if not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= end <= line_count:
                continue
            kind = str(meta.get("type") or "definition").removeprefix("code_")
            seen.setdefault((start, end), _Definition(start, end, name, kind))
    roots: List[_Definition] = []
    stack: List[_Definition] = []
    for definition in sorted(seen.values(), key=lambda d: (d.start, -d.end)):
        while stack and stack[-1].end < definition.start:
            stack.pop()
        if stack and definition.end > stack[-1].end:
            continue
        (stack[-1].children if stack else roots).append(definition)
        stack.append(definition)
    return roots


def partition_lines(lines: Sequence[str], roots: Sequence[_Definition], max_chars: int) -> List[Tuple[int, int]]:
    """Split the file top-down on definitions until pieces fit, then merge small neighbours."""
    # prefix[i] is the character count of lines 1..i, so any span's size is O(1).
    prefix = [0]
    for line in lines:
        prefix.append(prefix[-1] + len(line) + 1)

    def size(start: int, end: int) -> int:
        return prefix[end] - prefix[start - 1]

    def split(start: int, end: int, children: Sequence[_Definition]) -> List[Tuple[int, int]]:
        if size(start, end) <= max_chars:
            return [(start, end)]
        atoms: List[Tuple[int, int]] = []
        cursor = start
        for child in children:
            if child.start > cursor:
                atoms += pack_lines(lines[cursor - 1 : child.start - 1], cursor, max_chars)
            atoms += split(child.start, child.end, child.children)
            cursor = child.end + 1
        if cursor <= end:
            atoms += pack_lines(lines[cursor - 1 : end], cursor, max_chars)
        return _merge(atoms, size, max_chars)

    return split(1, len(lines), roots) if lines else []


def _merge(atoms: List[Tuple[int, int]], size, max_chars: int) -> List[Tuple[int, int]]:  # type: ignore[no-untyped-def]
    merged: List[Tuple[int, int]] = []
    for start, end in atoms:
        if merged and size(merged[-1][0], end) <= max_chars:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _enclosing(roots: Sequence[_Definition], start: int, end: int) -> List[_Definition]:
    chain: List[_Definition] = []
    level = roots
    while True:
        inner = next((d for d in level if d.start <= start and end <= d.end), None)
        if inner is None:
            return chain
        chain.append(inner)
        level = inner.children


def _first_inside(roots: Sequence[_Definition], start: int, end: int) -> Optional[_Definition]:
    for definition in roots:
        if start <= definition.start <= end:
            return definition
        if definition.start <= start <= definition.end:
            found = _first_inside(definition.children, start, end)
            if found is not None:
                return found
    return None


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return Path(path).read_text(encoding="latin-1")


def partition_code_document(document: ParsedDocument, max_chars: int) -> ParsedDocument:
    """Replace a code document's chunks with a definition-aligned partition of the file."""
    try:
        text = _read(document.file_path)
    except OSError:
        return document
    lines = text.splitlines()
    source = list(document.chunks)
    language = next((c.language for c in source if c.language), None)
    roots = _definitions(source, len(lines))
    spans = [s for s in partition_lines(lines, roots, max_chars) if any(lines[i - 1].strip() for i in range(s[0], s[1] + 1))]
    if not spans:
        return document

    chunks: List[ParserChunk] = []
    for start, end in spans:
        chain = _enclosing(roots, start, end)
        owner = chain[-1] if chain else _first_inside(roots, start, end)
        chunks.append(ParserChunk(
            content="\n".join(lines[start - 1 : end]),
            content_type="CODE",
            language=language,
            line_start=start,
            line_end=end,
            element_type=owner.kind if owner else "code_block",
            element_name=owner.name if owner else "",
            parent_id=chain[-2].name if len(chain) > 1 else "",
            metadata={"scope": " > ".join(f"{d.kind} {d.name}" for d in chain), "chunker": CHUNKER_VERSION},
        ))

    def home(line: Optional[int]) -> ParserChunk:
        if line is None or line < 1:
            return chunks[0]
        for chunk, (start, end) in zip(chunks, spans):
            if start <= line <= end:
                return chunk
        return chunks[-1] if line > spans[-1][1] else next(c for c, s in zip(chunks, spans) if s[0] > line)

    # Definition chunks place their symbols first; the whole-file chunk repeats
    # every symbol and only contributes ones no definition chunk carried.
    placed: set = set()
    for legacy in sorted(source, key=lambda c: c.element_type == "code_full"):
        target = home(legacy.line_start)
        for symbol in legacy.symbols or []:
            if symbol in placed:
                continue
            placed.add(symbol)
            target.symbols.append(symbol)
            meta = dict((legacy.symbol_metadata or {}).get(symbol, {}))
            meta.setdefault("parent_scope", legacy.parent_id or "")
            target.symbol_metadata[symbol] = meta
        target.relationships.extend(legacy.relationships or [])
        for symbol, ranking in (legacy.symbol_rankings or {}).items():
            target.symbol_rankings.setdefault(symbol, ranking)

    metadata = dict(document.metadata or {})
    metadata["chunker"] = CHUNKER_VERSION
    return ParsedDocument(doc_id=document.doc_id, file_path=document.file_path, chunks=chunks, metadata=metadata)
