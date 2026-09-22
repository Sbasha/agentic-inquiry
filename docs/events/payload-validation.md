# Event Payload Validation

Event payload validation provides type-safe event emission using Pydantic models. This feature ensures that event metadata conforms to expected schemas and provides better developer experience through IDE autocomplete and type checking.

## Overview

The event system supports two modes of operation:

1. **Untyped (backwards-compatible)**: Emit events with arbitrary metadata dictionaries
2. **Typed (recommended)**: Emit events with validated Pydantic payload models

Both modes are fully compatible and can be used interchangeably within the same codebase.

## Why Use Payload Validation?

### Benefits

- **Type Safety**: Catch invalid event data at creation time, not at query time
- **IDE Support**: Full autocomplete and type hints for event payloads
- **Documentation**: Self-documenting event schemas through Pydantic models
- **Validation**: Automatic validation of required fields, data types, and constraints
- **Evolution**: Versioned schemas support safe evolution of event structures
- **Backwards Compatibility**: Extra fields are allowed, supporting migration scenarios

### Use Cases

- **Critical Events**: Use typed payloads for events that drive system behavior
- **Public APIs**: Provide typed payload models for MCP tools and external integrations
- **Testing**: Validate event emissions in tests without manual assertion code
- **Debugging**: Catch schema mismatches early during development

## Quick Start

### Basic Usage

```python
from agentic_inquiry.events import EventSystem, EventTypes
from agentic_inquiry.events.payloads import IndexingStartedPayload
from agentic_inquiry.events.models import EventStatus

# Create a typed payload
payload = IndexingStartedPayload(
    path="/path/to/file",
    content_type="code",
    file_count=42
)

# Emit event with typed payload
async with EventSystem.from_config(config) as event_system:
    await event_system.emit_typed(
        EventTypes.Indexing.STARTED,
        source="pipeline",
        payload=payload,
        status=EventStatus.STARTED
    )
```

### Validation Errors

Invalid payloads raise `ValidationError` at creation time:

```python
from pydantic import ValidationError
from agentic_inquiry.events.payloads import IndexingStartedPayload

try:
    # Missing required field 'content_type'
    payload = IndexingStartedPayload(path="/path")
except ValidationError as e:
    print(f"Validation failed: {e}")
```

## Available Payload Models

### Indexing Events

```python
from agentic_inquiry.events.payloads import (
    IndexingStartedPayload,
    IndexingProgressPayload,
    IndexingCompletedPayload,
    IndexingFailedPayload,
    IndexingFileIndexedPayload,
    IndexingFileSkippedPayload,
    IndexingFileFailedPayload,
)

# Example: Progress event
payload = IndexingProgressPayload(
    files_processed=10,
    chunks_created=50,
    entities_created=25
)
```

### Search Events

```python
from agentic_inquiry.events.payloads import (
    SearchQueryStartedPayload,
    SearchQueryCompletedPayload,
    SearchQueryFailedPayload,
    SearchResultsReturnedPayload,
)

# Example: Search started with literal type validation
payload = SearchQueryStartedPayload(
    search_type="vector",  # Must be: vector, fts, hybrid, or graph
    query_text="find authentication code",
    limit=10
)
```

### Memory Events

```python
from agentic_inquiry.events.payloads import (
    MemoryStoredPayload,
    MemoryRetrievedPayload,
    MemoryConsolidatedPayload,
)

# Example: Memory stored with importance validation
payload = MemoryStoredPayload(
    memory_id="mem_123",
    tier="episodic",  # Must be: working, episodic, or semantic
    agent_id="agent_001",
    importance=0.8,  # Must be between 0.0 and 1.0
    content_length=256
)
```

### File Watching Events

```python
from agentic_inquiry.events.payloads import (
    WatchingStartedPayload,
    WatchingStoppedPayload,
    WatchingFileChangedPayload,
)

# Example: File changed event
payload = WatchingFileChangedPayload(
    file_path="/path/to/file.py",
    event_type="modified",  # Must be: created, modified, or deleted
    change_hash="abc123"
)
```

### Parsing Events

```python
from agentic_inquiry.events.payloads import (
    ParsingStartedPayload,
    ParsingCompletedPayload,
    ParsingFailedPayload,
    ParserSelectedPayload,
)
```

### Project Lifecycle Events

```python
from agentic_inquiry.events.payloads import (
    ProjectInitializedPayload,
    ProjectLoadedPayload,
    ProjectClosedPayload,
)
```

### System Events

```python
from agentic_inquiry.events.payloads import (
    SystemStartedPayload,
    SystemStoppedPayload,
    SystemErrorPayload,
)

# Example: System error with severity levels
payload = SystemErrorPayload(
    component="SearchService",
    error="Connection timeout",
    error_type="TimeoutError",
    severity="high"  # Must be: low, medium, high, or critical
)
```

## Advanced Usage

### Creating Custom Payload Models

Extend `BaseEventPayload` for custom event types:

```python
from agentic_inquiry.events.payloads import BaseEventPayload
from pydantic import Field

class CustomAnalysisPayload(BaseEventPayload):
    """Payload for custom analysis events."""

    analysis_type: str = Field(..., description="Type of analysis")
    score: float = Field(..., ge=0.0, le=1.0, description="Analysis score")
    findings: list[str] = Field(default_factory=list, description="Findings")
    metadata: dict[str, str] = Field(default_factory=dict)

# Use custom payload
payload = CustomAnalysisPayload(
    analysis_type="security",
    score=0.85,
    findings=["No critical issues", "2 warnings"]
)

await event_system.emit_typed(
    "analysis.completed",
    source="analyzer",
    payload=payload
)
```

### Validating Existing Event Metadata

Validate metadata from stored events:

```python
from agentic_inquiry.events.payloads import IndexingStartedPayload

# Retrieve event from store
events = await event_store.get_operation_events(operation_id)

for event in events:
    if event.event_type == "indexing.started":
        # Validate metadata against schema
        payload = event.validate_payload(IndexingStartedPayload)
        print(f"Indexing started for: {payload.path}")
```

### Creating Events Directly from Payloads

Use `Event.from_payload()` for type-safe event creation:

```python
from agentic_inquiry.events.models import Event, EventStatus
from agentic_inquiry.events.payloads import IndexingCompletedPayload

payload = IndexingCompletedPayload(
    files_processed=42,
    chunks_created=100,
    entities_created=50,
    relationships_created=75,
    success=True
)

event = Event.from_payload(
    event_type="indexing.completed",
    source="pipeline",
    payload=payload,
    project_id="my_project",
    status=EventStatus.COMPLETED
)
```

### Payload to Metadata Conversion

All payloads can convert to metadata dictionaries:

```python
payload = IndexingStartedPayload(path="/path", content_type="code")

# Convert to metadata dict
metadata = payload.to_metadata()
# Result: {"path": "/path", "content_type": "code"}

# Use in untyped emit
await event_system.emit(
    "indexing.started",
    source="pipeline",
    **metadata
)
```

## Migration Guide

### Migrating from Untyped to Typed Events

**Before (untyped)**:
```python
await event_system.emit(
    "indexing.started",
    source="pipeline",
    path="/path/to/file",
    content_type="code",
    file_count=42
)
```

**After (typed)**:
```python
from agentic_inquiry.events.payloads import IndexingStartedPayload

payload = IndexingStartedPayload(
    path="/path/to/file",
    content_type="code",
    file_count=42
)

await event_system.emit_typed(
    "indexing.started",
    source="pipeline",
    payload=payload
)
```

### Gradual Migration Strategy

1. **Identify Critical Events**: Start with events that drive system behavior
2. **Add Type Hints**: Document expected metadata structure
3. **Create Payloads**: Define Pydantic models for those events
4. **Update Emitters**: Use `emit_typed()` for new code
5. **Validate Legacy**: Add validation to event consumers
6. **Deprecate Untyped**: Gradually phase out untyped emissions

### Backwards Compatibility

The payload system is fully backwards compatible:

- **Extra fields allowed**: Payloads accept extra fields for migration scenarios
- **Optional validation**: Use `emit()` for untyped or `emit_typed()` for typed
- **Legacy events**: Existing events work without modification
- **Mixed usage**: Typed and untyped events coexist in the same system

## Field Validation Features

### Required vs Optional Fields

```python
class ExamplePayload(BaseEventPayload):
    required_field: str  # Must be provided
    optional_field: Optional[str] = None  # Can be omitted
```

### Numeric Constraints

```python
from pydantic import Field

class ScorePayload(BaseEventPayload):
    score: float = Field(..., ge=0.0, le=1.0)  # Between 0 and 1
    count: int = Field(..., ge=0)  # Non-negative
```

### Literal Types (Enums)

```python
from typing import Literal

class EventTypePayload(BaseEventPayload):
    event_type: Literal["created", "modified", "deleted"]
```

### Collections

```python
class CollectionPayload(BaseEventPayload):
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
```

### Custom Validators

```python
from pydantic import field_validator

class CustomPayload(BaseEventPayload):
    path: str

    @field_validator('path')
    @classmethod
    def validate_path(cls, v: str) -> str:
        if not v.startswith('/'):
            raise ValueError('Path must be absolute')
        return v
```

## Testing with Payloads

### Unit Testing Event Emissions

```python
import pytest
from agentic_inquiry.events.payloads import IndexingStartedPayload
from pydantic import ValidationError

def test_indexing_started_payload_valid():
    """Test payload creation with valid data."""
    payload = IndexingStartedPayload(
        path="/path/to/file",
        content_type="code"
    )
    assert payload.path == "/path/to/file"

def test_indexing_started_payload_invalid():
    """Test payload validation catches missing fields."""
    with pytest.raises(ValidationError):
        IndexingStartedPayload(path="/path")  # Missing content_type
```

### Integration Testing

```python
@pytest.mark.asyncio
async def test_typed_event_emission(event_system):
    """Test end-to-end typed event emission."""
    payload = IndexingStartedPayload(
        path="/test/path",
        content_type="code"
    )

    await event_system.emit_typed(
        "indexing.started",
        source="test",
        payload=payload
    )

    # Verify event was stored correctly
    events = await event_system.store.get_events_by_type("indexing.started")
    assert len(events) > 0

    # Validate stored metadata
    stored_payload = events[0].validate_payload(IndexingStartedPayload)
    assert stored_payload.path == "/test/path"
```

## Performance Considerations

### Validation Overhead

Pydantic validation adds minimal overhead (~microseconds per event):

```python
# For high-frequency events, consider untyped emission
for i in range(10000):
    await event_system.emit("progress", source="loop", iteration=i)

# For critical events, use typed payloads
payload = IndexingCompletedPayload(...)
await event_system.emit_typed("indexing.completed", source="pipeline", payload=payload)
```

### Caching Payload Models

Reuse payload instances when possible:

```python
# Inefficient: Creates new payload each iteration
for file in files:
    payload = IndexingFileIndexedPayload(file_path=file, chunks_created=10, entities_created=5)
    await event_system.emit_typed("indexing.file.indexed", source="pipeline", payload=payload)

# Better: Create payload instances as needed, let Pydantic optimize
for file in files:
    # Pydantic is optimized for repeated validation
    await event_system.emit_typed(
        "indexing.file.indexed",
        source="pipeline",
        payload=IndexingFileIndexedPayload(file_path=file, chunks_created=10, entities_created=5)
    )
```

## Best Practices

1. **Use Typed Payloads for Public APIs**: MCP tools, external integrations
2. **Validate Critical Events**: Events that trigger system behavior
3. **Document Schemas**: Add clear descriptions to all fields
4. **Version Schemas**: Use schema_version for breaking changes
5. **Allow Extra Fields**: Support migration with `extra="allow"`
6. **Test Validation**: Add unit tests for invalid payloads
7. **Gradual Migration**: Start with high-value events first
8. **Monitor Errors**: Log validation failures for debugging

## Troubleshooting

### Common Validation Errors

**Missing required field**:
```python
ValidationError: 1 validation error for IndexingStartedPayload
content_type
  Field required [type=missing, input_value={'path': '/path'}, input_type=dict]
```
→ Solution: Provide all required fields

**Invalid type**:
```python
ValidationError: 1 validation error for MemoryStoredPayload
importance
  Input should be less than or equal to 1.0 [type=less_than_equal, input_value=1.5, input_type=float]
```
→ Solution: Check field constraints (min/max values, allowed literals)

**Extra field rejected**:
```python
# Should not happen with BaseEventPayload (extra="allow")
# But if you override config:
ValidationError: Extra inputs are not permitted
```
→ Solution: Use `extra="allow"` in model config

### Debugging Validation Issues

Enable verbose Pydantic errors:

```python
from pydantic import ValidationError

try:
    payload = SomePayload(invalid="data")
except ValidationError as e:
    print(e.json())  # Detailed JSON error report
```

## See Also

- [Event System Overview](../events/README.md)
- [Event Types Reference](../events/event-types.md)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [API Reference: Event Models](../api/events/models.md)
- [API Reference: Payload Models](../api/events/payloads.md)
