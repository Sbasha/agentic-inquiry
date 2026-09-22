# Test Helpers

This directory contains reusable test utilities for the Agentic Inquiry test suite.

## Modules

### `async_utils.py`

Provides utilities for async testing patterns:

- **`AsyncTestHelper.wait_for_condition()`**: Replace fixed `asyncio.sleep()` calls with condition polling
- **`AsyncTestHelper.ensure_cleanup()`**: Ensure all async operations complete in fixture cleanup

**Example usage:**

```python
from tests.helpers import AsyncTestHelper

async def test_indexing():
    await pipeline.index_file("test.py")
    
    # Wait for condition instead of fixed sleep
    success = await AsyncTestHelper.wait_for_condition(
        lambda: db.count_chunks() > 0,
        timeout=5.0
    )
    assert success, "File was not indexed in time"

@pytest.fixture
async def my_fixture():
    resource = await create_resource()
    yield resource
    # Ensure cleanup completes
    await AsyncTestHelper.ensure_cleanup(
        resource.close(),
        resource.cleanup()
    )
```

### `assertions.py`

Custom assertion helpers for common test patterns:

- **`assert_chunks_equal()`**: Compare two chunks with optional field exclusion
- **`assert_valid_embedding()`**: Validate embedding vectors

**Example usage:**

```python
from tests.helpers.assertions import assert_chunks_equal, assert_valid_embedding

def test_chunk_equality():
    assert_chunks_equal(chunk1, chunk2, ignore_fields=["chunk_id"])

def test_embedding():
    assert_valid_embedding(embedding, expected_dim=384)
```

### `factories.py`

Factory functions for creating test data:

- **`create_test_chunk()`**: Create DocumentChunk instances
- **`create_test_parsed_document()`**: Create ParsedDocument instances

**Example usage:**

```python
from tests.helpers.factories import create_test_chunk, create_test_parsed_document

def test_with_chunk():
    chunk = create_test_chunk(
        content="test content",
        doc_id="doc_1",
        metadata={"key": "value"}
    )
    # Use chunk in test...

def test_with_document():
    doc = create_test_parsed_document(
        file_path="test.py",
        language="python"
    )
    # Use document in test...
```

## Guidelines

### When to Add Helpers

Add helpers to this directory when:

1. The same pattern appears in 3+ test files
2. The pattern is complex enough to warrant abstraction
3. The helper improves test readability and maintainability

### When NOT to Add Helpers

Don't add helpers for:

1. Simple one-line operations
2. Test-specific logic that won't be reused
3. Patterns that are clearer when written inline

### Naming Conventions

- Use descriptive names that indicate purpose
- Prefix assertion helpers with `assert_`
- Prefix factory functions with `create_`
- Use `AsyncTestHelper` for async utilities

## Importing Helpers

Import helpers from the top-level package:

```python
from tests.helpers import AsyncTestHelper
from tests.helpers.assertions import assert_chunks_equal
from tests.helpers.factories import create_test_chunk
```

## Testing Helpers

Test helpers should themselves be tested. Add tests for helpers in `tests/helpers/test_*.py` files.

## Best Practices

### Async Testing Patterns

**DO use condition polling:**
```python
# ✅ GOOD: Wait for condition with timeout
success = await AsyncTestHelper.wait_for_condition(
    lambda: db.count_chunks() > 0,
    timeout=5.0,
    poll_interval=0.01
)
assert success, "Condition not met in time"
```

**DON'T use fixed sleeps:**
```python
# ❌ BAD: Fixed sleep is unreliable and slow
await asyncio.sleep(1.0)
assert db.count_chunks() > 0
```

### Fixture Cleanup

**DO ensure all async operations complete:**
```python
# ✅ GOOD: Explicit cleanup
@pytest.fixture
async def my_fixture():
    resource = await create_resource()
    yield resource
    await AsyncTestHelper.ensure_cleanup(
        resource.close(),
        resource.cleanup()
    )
```

**DON'T forget to await cleanup:**
```python
# ❌ BAD: Cleanup may not complete
@pytest.fixture
async def my_fixture():
    resource = await create_resource()
    yield resource
    resource.close()  # Not awaited!
```

### Test Data Creation

**DO use factories for consistency:**
```python
# ✅ GOOD: Factory ensures valid test data
chunk = create_test_chunk(
    content="test content",
    metadata={"key": "value"}
)
```

**DON'T create test data inline repeatedly:**
```python
# ❌ BAD: Duplicated test data creation
chunk = DocumentChunk(
    chunk_id="test_1",
    doc_id="doc_1",
    content="test content",
    embedding=[0.1] * 384,
    metadata={"key": "value"},
    # ... many more fields
)
```

## Migration from Old Patterns

### Replacing asyncio.sleep()

**Before:**
```python
async def test_indexing():
    await pipeline.index_file("test.py")
    await asyncio.sleep(1.0)  # Hope it's done
    assert db.count_chunks() > 0
```

**After:**
```python
async def test_indexing():
    await pipeline.index_file("test.py")
    success = await AsyncTestHelper.wait_for_condition(
        lambda: db.count_chunks() > 0,
        timeout=5.0
    )
    assert success
```

### Consolidating Duplicate Helpers

**Before (duplicated across test files):**
```python
# In test_indexing.py
async def wait_for_chunks(db, expected_count):
    for _ in range(50):
        if db.count_chunks() >= expected_count:
            return True
        await asyncio.sleep(0.1)
    return False

# In test_search.py
async def wait_for_chunks(db, expected_count):
    # Same implementation duplicated
    ...
```

**After (consolidated in helpers):**
```python
# In tests/helpers/async_utils.py
class AsyncTestHelper:
    @staticmethod
    async def wait_for_condition(condition_fn, timeout=5.0):
        # Single implementation used everywhere
        ...

# In all test files
from tests.helpers import AsyncTestHelper
success = await AsyncTestHelper.wait_for_condition(
    lambda: db.count_chunks() >= expected_count
)
```

## Performance Considerations

### Timeout Values

Choose appropriate timeouts based on operation type:

```python
# Fast operations (in-memory)
await AsyncTestHelper.wait_for_condition(
    lambda: cache.has_key("test"),
    timeout=1.0  # 1 second is plenty
)

# Medium operations (database)
await AsyncTestHelper.wait_for_condition(
    lambda: db.count_chunks() > 0,
    timeout=5.0  # 5 seconds for DB operations
)

# Slow operations (indexing, embedding)
await AsyncTestHelper.wait_for_condition(
    lambda: pipeline.is_complete(),
    timeout=30.0  # 30 seconds for complex operations
)
```

### Poll Intervals

Adjust poll intervals based on expected timing:

```python
# Fast-changing conditions
await AsyncTestHelper.wait_for_condition(
    lambda: flag.is_set(),
    poll_interval=0.01  # Check every 10ms
)

# Slow-changing conditions
await AsyncTestHelper.wait_for_condition(
    lambda: file_exists("output.txt"),
    poll_interval=0.1  # Check every 100ms
)
```

## Common Patterns

### Testing Async Pipelines

```python
async def test_pipeline():
    # Start pipeline
    await pipeline.start()
    
    # Wait for ready state
    await AsyncTestHelper.wait_for_condition(
        lambda: pipeline.is_ready(),
        timeout=5.0
    )
    
    # Process data
    await pipeline.process(data)
    
    # Wait for completion
    await AsyncTestHelper.wait_for_condition(
        lambda: pipeline.is_complete(),
        timeout=10.0
    )
    
    # Verify results
    results = await pipeline.get_results()
    assert len(results) > 0
```

### Testing Database Operations

```python
async def test_database():
    # Insert data
    await db.insert(chunks)
    
    # Wait for data to be available
    await AsyncTestHelper.wait_for_condition(
        lambda: db.count_chunks() == len(chunks),
        timeout=5.0
    )
    
    # Query and verify
    results = await db.search("query")
    assert len(results) > 0
```

### Testing Event Systems

```python
async def test_events():
    events_received = []
    
    def handler(event):
        events_received.append(event)
    
    event_bus.subscribe("test_event", handler)
    
    # Trigger event
    await event_bus.publish("test_event", {"data": "value"})
    
    # Wait for event processing
    await AsyncTestHelper.wait_for_condition(
        lambda: len(events_received) > 0,
        timeout=1.0
    )
    
    assert events_received[0]["data"] == "value"
```
