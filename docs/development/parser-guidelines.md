# Parser Implementation Guidelines

This document provides essential guidelines for implementing parsers that work correctly with the indexing pipeline and LanceDB storage.

## Chunk metadata

`ParserChunk.metadata` accepts any JSON-serializable values: strings,
numbers, booleans, `None`, lists and nested dicts. The indexing pipeline
serializes the whole dict to a JSON string in the `metadata.data` column of
`document_chunks` (`agentic_inquiry/indexing/schema_processor.py`), so the
table schema does not change with the keys a parser emits.

If the dict holds a value `json.dumps` cannot encode (a `Path`, a `datetime`,
an arbitrary object), the pipeline logs a warning and stores `{}` for that
chunk's metadata: every key is lost, not only the bad one. Convert such values
to strings before building the chunk.

Prefer a top-level `ParserChunk` field when one exists for the data (below):
top-level fields are real columns that search and filtering can use, while
`metadata` is an opaque JSON blob.

## ParserChunk Field Reference

### Top-Level Fields (Preferred)

Use these fields instead of putting data in metadata:

- `content` (str) - The actual text content
- `fts_text` (str) - Full-text search optimized text
- `symbols` (List[str]) - Extracted symbols (functions, classes, headings, entities)
- `language` (str) - Programming language or document language
- `content_type` (str) - "CODE", "PROSE", "TABLE", etc.
- `page_number` (int) - Page number for documents
- `line_start` (int) - Starting line number
- `line_end` (int) - Ending line number
- `element_type` (str) - Type of element (function, class, heading, etc.)
- `element_name` (str) - Name of the element
- `parent_id` (str) - ID of parent chunk
- `child_ids` (List[str]) - IDs of child chunks
- `relationships` (List[ParserRelationship]) - Relationships to other entities

### Metadata Dict

Parser-specific detail with no top-level field. Stored as one JSON string, so
it is returned with the chunk but not searchable or filterable by key.

### Ranking Signals Dict

For scores, metrics, and computed values:

- `"complexity"` (float) - Code complexity score
- `"importance"` (float) - Importance score
- `"confidence"` (float) - Confidence score
- Any other numeric metrics

### Symbol Metadata/Rankings Dicts

For per-symbol information:

- `symbol_metadata` (Dict[str, Dict]) - Metadata for each symbol
- `symbol_rankings` (Dict[str, Dict]) - Rankings for each symbol

These are automatically serialized to JSON strings by the indexing pipeline.

## Testing Your Parser

Always test your parser with mixed content:

```python
# Test with both code and documents
files = [
    "simple.py",      # Code file
    "README.md",      # Document file
    "config.json",    # Structured data
]

for file in files:
    parsed = parser.parse(file)
    # Index in same database
    await pipeline.process_document(parsed)
```

If a chunk comes back with empty metadata, look for a "Failed to serialize
chunk metadata" warning: a value in the dict was not JSON-serializable.

## Examples

### Code Parser Example

```python
def parse(self, path: str) -> ParsedDocument:
    # ... parsing logic ...
    
    chunks = []
    for symbol in extracted_symbols:
        chunk = ParserChunk(
            content=symbol.content,
            symbols=[symbol.name],
            language="python",
            line_start=symbol.start_line,
            line_end=symbol.end_line,
            element_type="function",
            element_name=symbol.name,
            metadata={
                "element_type": "function",      # ✅ Simple, consistent
                "content_type": "CODE",          # ✅ Simple, consistent
            },
            ranking_signals={
                "complexity": symbol.complexity,  # ✅ Metrics here
            },
            symbol_metadata={
                symbol.name: {
                    "type": "function",
                    "params": symbol.params,
                }
            }
        )
        chunks.append(chunk)
    
    return ParsedDocument(
        doc_id=generate_id(path),
        file_path=path,
        chunks=chunks
    )
```

### Document Parser Example

```python
def parse(self, path: str) -> ParsedDocument:
    # ... parsing logic ...
    
    chunks = []
    for section in extracted_sections:
        chunk = ParserChunk(
            content=section.text,
            symbols=[section.heading],           # ✅ Headings as symbols
            page_number=section.page,
            element_type="section",
            element_name=section.heading,
            metadata={
                "element_type": "section",       # ✅ Simple, consistent
                "content_type": "PROSE",         # ✅ Simple, consistent
            }
        )
        chunks.append(chunk)
    
    return ParsedDocument(
        doc_id=generate_id(path),
        file_path=path,
        chunks=chunks
    )
```

## Summary

**Golden Rules:**
1. Use top-level ParserChunk fields whenever possible
2. Keep metadata simple: only str, int, float, bool, None
3. Put metrics in ranking_signals
4. Put complex data in symbol_metadata/symbol_rankings
5. Keep metadata fields consistent across all file types
6. Test with mixed content (code + docs) before deploying

Following these guidelines will ensure your parser works reliably with the indexing pipeline and LanceDB storage.
