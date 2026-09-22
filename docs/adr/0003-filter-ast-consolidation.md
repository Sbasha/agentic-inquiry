# ADR-003: Filter AST Consolidation

## Status
Accepted

## Context
Multiple search operations (vector, FTS, hybrid) required filtering by metadata. Each implementation had its own filter representation:
- LanceDB used SQL-like strings
- Graph queries used dict-based filters
- Memory search used separate parameters

This caused:
- Inconsistent filtering behavior across tools
- Duplicated filter parsing logic
- Bugs when filter syntax varied between backends

From retrospective analysis: Filter-related issues appeared in 48% of entity mismatch bugs.

## Decision
Consolidate all filter representations into a single **Filter AST** (Abstract Syntax Tree):

1. **Unified FilterNode types**: AND, OR, NOT, comparison operators
2. **Single parser**: Converts user input to AST
3. **Backend translators**: Convert AST to backend-specific format
4. **Validation at AST level**: Catch invalid filters early

Example:
```python
# User provides dict-based filter
filter_input = {"type": "function", "language": "python"}

# Parsed to AST
ast = AndNode([
    CompareNode("type", "=", "function"),
    CompareNode("language", "=", "python")
])

# Translated for LanceDB
sql = "type = 'function' AND language = 'python'"

# Translated for graph query
graph_filter = {"$and": [{"type": "function"}, {"language": "python"}]}
```

## Consequences

### Positive
- **Consistency**: Same filter syntax works everywhere
- **Validation**: Invalid filters caught at parse time
- **Extensibility**: Add new backends without changing filter API
- **Debugging**: AST provides clear representation of filter intent

### Negative
- **Complexity**: Additional abstraction layer
- **Performance**: Parse + translate vs direct string
- **Learning curve**: Developers must understand AST structure

### Mitigations
- Most filters auto-detected, users rarely write AST directly
- Performance impact minimal (microseconds)
- Helper functions for common filter patterns
- Documentation in `database/filter_helpers.py`

## References
- `agent_vault/database/filter_helpers.py` - Filter utilities
- `agent_vault/database/lancedb_manager.py` - LanceDB translation
- tests/database/test_filter_helpers.py - Filter tests
- Retrospective: 05-ARCHITECTURE-DECISION-ANALYSIS.md
