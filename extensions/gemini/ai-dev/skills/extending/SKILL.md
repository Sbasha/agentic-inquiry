---
name: extending
description: How to extend Agentic Inquiry - add parsers, tools, config options, entity types, and more.
---

# Extending Agentic Inquiry

Reference for adding new capabilities to the system.

## When to Use

- Adding new parser
- Creating new MCP tool
- Adding configuration options
- Extending the data model

## Extension Reference

| To Add | Reference |
|--------|-----------|
| New parser | `docs/development/parser-guidelines.md`, use `@register_parser` decorator |
| New MCP tool | `docs/mcp/README.md` |
| New config option | See Configuration section below |
| New entity type | Add to `EntityType` enum in `models/graph_entity.py` |
| New relationship type | Add to `RelationshipType` enum in `models/graph_relationship.py` with inverse |
| New search reranker | Configure `search.hybrid_search.reranker_type` |
| New memory tier | Extend `MemoryTier` enum, add layer in `memory/layers/` |
| New event type | Add to `EventTypes` in `events/types.py` |
| Custom consolidation | Extend `ConsolidationEngine` in `memory/consolidation.py` |

## Adding a Parser

```python
from agentic_inquiry.parsers.base import BaseParser, register_parser
from agentic_inquiry.parsers.models import ParserChunk

@register_parser("my_format", extensions=[".myf"])
class MyFormatParser(BaseParser):
    async def parse_file(self, file_path: Path) -> list[ParserChunk]:
        content = file_path.read_text()
        return [ParserChunk(
            content=content,
            file_path=str(file_path),
            chunk_type="my_format",
            start_line=1,
            end_line=content.count("\n") + 1,
            metadata={"format": "my_format"}  # Only str/int/float/bool!
        )]
```

## Adding an MCP Tool

```python
from agentic_inquiry.mcp.tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something useful"

    async def execute(self, **params) -> dict:
        # Implementation
        return {"result": "success"}
```

## Adding Configuration

1. Add to schema: `config/config.schema.json`
2. Add default: `config/default.yaml`
3. Document: `docs/configuration.md`

```yaml
# config/default.yaml
my_feature:
  enabled: true
  max_items: 100
```

## Adding Entity Types

```python
# models/graph_entity.py
class EntityType(str, Enum):
    FUNCTION = "function"
    CLASS = "class"
    MY_TYPE = "my_type"  # Add new type
```

## Adding Relationship Types

```python
# models/graph_relationship.py
class RelationshipType(str, Enum):
    CALLS = "calls"
    CALLED_BY = "called_by"  # Include inverse!
    MY_REL = "my_rel"
    MY_REL_INVERSE = "my_rel_inverse"

# Also update INVERSE_MAP
INVERSE_MAP = {
    RelationshipType.MY_REL: RelationshipType.MY_REL_INVERSE,
    ...
}
```
