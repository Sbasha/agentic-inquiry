# ADR-001: Protocol-Based Storage Architecture

## Status
Accepted

## Context
The storage layer required multiple implementations (vector search, graph operations, FTS, memory) that needed to work together seamlessly. Initial implementations had tight coupling between components, making it difficult to:
- Swap storage backends
- Test components in isolation
- Add new storage capabilities
- Maintain clear contracts between layers

From retrospective analysis: 27 protocol definitions emerged to handle various storage operations, but runtime type checking was needed to support duck-typing patterns.

## Decision
Adopt a protocol-based architecture using Python's `typing.Protocol` with `@runtime_checkable`:

1. **27 granular protocols** define explicit contracts for each storage capability
2. **@runtime_checkable decorator** enables duck-typing verification
3. **Composition over inheritance** - providers implement multiple protocols
4. **Clear separation** between vector, graph, FTS, and memory operations

Example:
```python
@runtime_checkable
class VectorSearchProtocol(Protocol):
    async def search_similar(self, query_vector: list[float], limit: int) -> list[SearchResult]: ...

@runtime_checkable
class GraphProtocol(Protocol):
    async def traverse(self, start_id: str, depth: int) -> list[GraphNode]: ...
```

## Consequences

### Positive
- **Testability**: Mock any protocol in isolation
- **Flexibility**: Swap implementations without changing callers
- **Type Safety**: IDE autocomplete and static analysis work correctly
- **Documentation**: Protocols serve as living documentation of contracts

### Negative
- **Learning Curve**: 27 protocols requires familiarity with the architecture
- **Overhead**: Runtime checking has small performance cost
- **Complexity**: More files and abstractions than direct implementation

### Mitigations
- Protocols grouped by domain in `storage/protocols/`
- StorageFacade (see ADR-002) provides single entry point
- Documentation in AGENTS.md "Architecture" section

## References
- `agentic_inquiry/storage/protocols/` - Protocol definitions
- `agentic_inquiry/storage/providers/lancedb.py` - Reference implementation
- AGENTS.md "Architecture Principles" section
- Retrospective: 05-ARCHITECTURE-DECISION-ANALYSIS.md
