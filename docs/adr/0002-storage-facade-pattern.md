# ADR-002: Storage Facade Pattern

## Status
Accepted

## Context
With 27 protocols (ADR-001) and multiple storage providers, components had to:
- Know which protocol to use for each operation
- Manage provider lifecycle and connections
- Handle cross-cutting concerns (caching, error handling, transactions)

This led to scattered initialization code and inconsistent error handling.

From retrospective analysis: `storage/facade.py` was identified as a HIGH-risk fragile file (10 commits, 3 fix sessions) due to its central role.

## Decision
Implement a **StorageFacade** as the single entry point for all storage operations:

1. **Single constructor** - One place to initialize all storage
2. **Protocol delegation** - Facade exposes protocol methods, delegates to providers
3. **Consistent error handling** - All storage errors normalized at facade level
4. **Session scoping** - Facade owns session lifecycle for transactions

Example:
```python
class StorageFacade:
    def __init__(self, config: StorageConfig):
        self._vector = LanceDBProvider(config)
        self._graph = self._vector  # Same provider, different protocol

    # Vector operations
    async def search_similar(self, ...) -> list[SearchResult]:
        return await self._vector.search_similar(...)

    # Graph operations
    async def traverse(self, ...) -> list[GraphNode]:
        return await self._graph.traverse(...)
```

## Consequences

### Positive
- **Simplicity**: One import, one object for all storage
- **Consistency**: Error handling in one place
- **Discoverability**: IDE autocomplete shows all available operations
- **Testing**: Mock entire storage layer with one fake

### Negative
- **Single point of failure**: Bugs in facade affect all storage
- **God object risk**: Facade could grow too large
- **Indirection**: Additional call layer between callers and providers

### Mitigations
- Comprehensive test coverage for facade (see tests/storage/test_facade.py)
- Keep facade thin - only delegation, no business logic
- Document as fragile area in AGENTS.md

## References
- `agent_vault/storage/facade.py` - Implementation
- ADR-001 - Protocol architecture (prerequisite)
- AGENTS.md "Fragile Areas" section
- Retrospective: 05-ARCHITECTURE-DECISION-ANALYSIS.md
