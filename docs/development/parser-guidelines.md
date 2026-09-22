# Parser Implementation Guidelines

This document provides essential guidelines for implementing parsers that work correctly with the indexing pipeline and LanceDB storage.

## Critical Constraints

### Metadata Field Constraints

**IMPORTANT**: The `metadata` dict in `ParserChunk` has strict constraints due to how LanceDB handles schema evolution. These constraints are now **enforced programmatically using Pydantic validators**.

#### The Problem

LanceDB infers the schema from the first document indexed. When subsequent documents have different metadata fields, LanceDB will reject them with schema mismatch errors like:
```
ValueError: Field 'complexity' not found in target schema
```

#### The Solution

**Only include simple, consistent fields in `metadata`:**

✅ **ALLOWED in metadata:**
- `str` - Simple strings
- `int` - Simple integers  
- `float` - Simple floats
- `bool` - Booleans
- `None` - Null values

❌ **NOT ALLOWED in metadata:**
- `list` - Lists (even of simple types)
- `dict` - Nested dictionaries
- Complex objects
- Fields that vary between file types

#### Automatic Validation

The `ParserChunk` model uses Pydantic validators to enforce these constraints at parse time:

```python
from pydantic import BaseModel, field_validator

class ParserChunk(BaseModel):
    content: str
    metadata: Dict[str, Union[str, int, float, bool, None]]
    
    @field_validator("metadata")
    @classmethod
    def validate_metadata_types(cls, v: Dict) -> Dict:
        """Ensure metadata contains only simple types."""
        for key, value in v.items():
            if isinstance(value, (list, dict)):
                raise ValueError(
                    f"Metadata field '{key}' contains complex type {type(value).__name__}. "
                    f"Only str, int, float, bool, and None are allowed. "
                    f"See docs/development/parser-guidelines.md for details."
                )
        return v
```

**What this means for parser developers:**
- Invalid metadata is caught immediately when creating `ParserChunk` instances
- Clear error messages reference this guideline document
- No need to wait for database insertion to discover schema issues
- Faster development cycle with immediate feedback

#### Best Practices

1. **Use top-level ParserChunk fields when possible:**
   ```python
   ParserChunk(
       content=text,
       symbols=["function1", "class1"],  # ✅ Use top-level field
       language="python",                 # ✅ Use top-level field
       line_start=10,                     # ✅ Use top-level field
       metadata={
           "element_type": "code_semantic",  # ✅ Simple string
           "content_type": "CODE",           # ✅ Simple string
       }
   )
   ```

2. **Store complex data in `ranking_signals`:**
   ```python
   ParserChunk(
       content=text,
       metadata={
           "element_type": "function",  # ✅ Simple
       },
       ranking_signals={
           "complexity": 5.2,           # ✅ Complexity goes here
           "importance": 0.8,           # ✅ Scores go here
       }
   )
   ```

3. **Serialize complex structures as JSON strings:**
   ```python
   import json
   
   ParserChunk(
       content=text,
       metadata={
           "element_type": "function",
       },
       symbol_metadata={                    # ✅ Use dedicated field
           "func1": {"type": "function"},
       },
       # OR if you must store in metadata:
       # metadata={
       #     "imports_json": json.dumps(imports_list),  # ✅ Serialize to string
       # }
   )
   ```

4. **Keep metadata fields consistent across all chunks:**
   - If you set `"element_type"` in one chunk, use it in all chunks
   - Use the same field names across different file types
   - Avoid file-type-specific fields in metadata

#### Common Mistakes

❌ **DON'T DO THIS:**
```python
# BAD: Lists in metadata
ParserChunk(
    content=text,
    metadata={
        "imports": ["os", "sys"],        # ❌ List will cause schema issues
        "elements": [{"name": "func"}],  # ❌ List of dicts
    }
)

# BAD: Nested dicts in metadata
ParserChunk(
    content=text,
    metadata={
        "symbol_info": {                 # ❌ Nested dict
            "name": "func",
            "type": "function"
        }
    }
)

# BAD: File-type-specific fields
ParserChunk(
    content=text,
    metadata={
        "complexity": 5,                 # ❌ Only in code files
        "page_number": 3,                # ❌ Only in PDF files
    }
)
```

✅ **DO THIS INSTEAD:**
```python
# GOOD: Use top-level fields
ParserChunk(
    content=text,
    symbols=["os", "sys"],               # ✅ Top-level field
    page_number=3,                       # ✅ Top-level field
    metadata={
        "element_type": "import",        # ✅ Simple, consistent
        "content_type": "CODE",          # ✅ Simple, consistent
    },
    ranking_signals={
        "complexity": 5,                 # ✅ In ranking_signals
    }
)
```

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

### Metadata Dict (Use Sparingly)

Only for simple, consistent fields:

- `"element_type"` (str) - Consistent across all chunks
- `"content_type"` (str) - Consistent across all chunks
- `"start_line"` (int) - If not using top-level line_start
- `"end_line"` (int) - If not using top-level line_end

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

If you get schema errors, check your metadata fields!

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
