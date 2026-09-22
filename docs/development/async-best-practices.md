# Async Best Practices

This document outlines best practices for working with async/await patterns in Agent-Vault.

## Event Loop Management

### Use get_running_loop() in Async Context

**Always use `asyncio.get_running_loop()` instead of the deprecated `asyncio.get_event_loop()` when running code in an async context.**

```python
import asyncio

# ✅ CORRECT: Use get_running_loop() in async functions
async def process_data(data):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, cpu_bound_operation, data)
    return result

# ❌ WRONG: Don't use get_event_loop() (deprecated in Python 3.10+)
async def process_data_wrong(data):
    loop = asyncio.get_event_loop()  # Deprecated!
    result = await loop.run_in_executor(None, cpu_bound_operation, data)
    return result
```

### Why This Matters

**`get_running_loop()` advantages:**
- Raises `RuntimeError` if called outside async context (catches bugs early)
- Always returns the correct event loop for the current async context
- Required for Python 3.10+ compatibility
- Prevents subtle bugs from using wrong event loop

**`get_event_loop()` problems:**
- Deprecated in Python 3.10+
- Can return wrong event loop in some contexts
- May create new event loop unexpectedly
- Silently fails in some edge cases

### When to Use Each Function

```python
# ✅ In async functions: Use get_running_loop()
async def async_function():
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, blocking_call)

# ✅ In sync code starting event loop: Use new_event_loop()
def sync_function():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(async_function())
    finally:
        loop.close()

# ✅ In sync code with existing loop: Use get_event_loop()
def sync_function_with_loop():
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop
```

## CPU-Bound Operations

### Run CPU-Bound Work in Executor

CPU-bound operations block the event loop. Use `run_in_executor()` to run them in a thread pool:

```python
import asyncio

async def parse_file(file_path: str):
    loop = asyncio.get_running_loop()
    
    # ✅ CORRECT: CPU-bound parsing in executor
    parsed = await loop.run_in_executor(
        None,  # Use default ThreadPoolExecutor
        tree_sitter_parse,
        file_content
    )
    
    return parsed

# ❌ WRONG: Blocking the event loop
async def parse_file_wrong(file_path: str):
    # This blocks the event loop!
    parsed = tree_sitter_parse(file_content)
    return parsed
```

### Common CPU-Bound Operations

These operations should run in an executor:

- **Parsing**: tree-sitter, unstructured library
- **Embedding generation**: Neural network inference
- **Compression**: gzip, bz2
- **Hashing**: SHA256, MD5
- **Serialization**: pickle, JSON (large objects)
- **Image processing**: PIL, OpenCV
- **Cryptography**: Encryption, decryption

```python
async def generate_embeddings(texts: List[str]):
    loop = asyncio.get_running_loop()
    
    # ✅ Run embedding generation in executor
    embeddings = await loop.run_in_executor(
        None,
        embedding_model.encode,
        texts
    )
    
    return embeddings
```

## I/O Operations

### Use Async I/O Libraries

Always use async I/O libraries for file and network operations:

```python
import aiofiles
import aiosqlite
import httpx

# ✅ CORRECT: Async file I/O
async def read_file(path: str) -> str:
    async with aiofiles.open(path, 'r') as f:
        return await f.read()

# ❌ WRONG: Blocking file I/O
async def read_file_wrong(path: str) -> str:
    with open(path, 'r') as f:  # Blocks event loop!
        return f.read()

# ✅ CORRECT: Async database
async def query_database(query: str):
    async with aiosqlite.connect("db.sqlite") as db:
        async with db.execute(query) as cursor:
            return await cursor.fetchall()

# ✅ CORRECT: Async HTTP
async def fetch_url(url: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.text
```

### Async Libraries in Agent-Vault

- **Files**: `aiofiles` for file I/O
- **SQLite**: `aiosqlite` for database operations
- **HTTP**: `httpx` for HTTP requests
- **LanceDB**: Custom async wrapper using `run_in_executor()`

## Concurrency Control

### Use Semaphores for Rate Limiting

Control concurrent operations with semaphores:

```python
import asyncio

class IndexingPipeline:
    def __init__(self, max_concurrent: int = 10):
        self._semaphore = asyncio.Semaphore(max_concurrent)
    
    async def index_file(self, file_path: str):
        # ✅ Limit concurrent operations
        async with self._semaphore:
            parsed = await self.parser.parse(file_path)
            await self.db.store(parsed)
```

### Gather for Parallel Execution

Use `asyncio.gather()` for parallel execution:

```python
# ✅ CORRECT: Parallel execution
async def index_multiple_files(files: List[str]):
    tasks = [index_file(f) for f in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results

# ❌ WRONG: Sequential execution
async def index_multiple_files_wrong(files: List[str]):
    results = []
    for f in files:
        result = await index_file(f)  # One at a time!
        results.append(result)
    return results
```

### Handle Exceptions in Gather

```python
# ✅ CORRECT: Handle exceptions
async def process_all(items: List[str]):
    tasks = [process_item(item) for item in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Check for exceptions
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("Failed to process %s: %s", items[i], result)
        else:
            logger.info("Processed %s successfully", items[i])
    
    return results
```

## Testing Async Code

### Use Condition Polling, Not Fixed Sleeps

```python
from tests.helpers import AsyncTestHelper

# ✅ CORRECT: Condition polling
async def test_indexing():
    await pipeline.index_file("test.py")
    
    success = await AsyncTestHelper.wait_for_condition(
        lambda: db.count_chunks() > 0,
        timeout=5.0,
        poll_interval=0.01
    )
    
    assert success, "File was not indexed in time"

# ❌ WRONG: Fixed sleep
async def test_indexing_wrong():
    await pipeline.index_file("test.py")
    await asyncio.sleep(1.0)  # Unreliable!
    assert db.count_chunks() > 0
```

### Ensure Fixture Cleanup

```python
import pytest
from tests.helpers import AsyncTestHelper

# ✅ CORRECT: Explicit cleanup
@pytest.fixture
async def db_manager():
    manager = await create_db_manager()
    yield manager
    await AsyncTestHelper.ensure_cleanup(
        manager.close(),
        manager.cleanup()
    )

# ❌ WRONG: Cleanup may not complete
@pytest.fixture
async def db_manager_wrong():
    manager = await create_db_manager()
    yield manager
    manager.close()  # Not awaited!
```

## Error Handling

### Use Try-Except in Async Functions

```python
# ✅ CORRECT: Proper error handling
async def safe_operation():
    try:
        result = await risky_operation()
        return result
    except SpecificError as e:
        logger.error("Operation failed: %s", e)
        return None
    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        raise

# ❌ WRONG: Unhandled exceptions
async def unsafe_operation():
    result = await risky_operation()  # May raise!
    return result
```

### Graceful Degradation

```python
# ✅ CORRECT: Graceful degradation
async def get_from_cache(key: str) -> Optional[Any]:
    try:
        return await cache.get(key)
    except CacheError as e:
        logger.warning("Cache lookup failed: %s", e)
        return None  # Graceful degradation

# ❌ WRONG: Crash on cache failure
async def get_from_cache_wrong(key: str) -> Any:
    return await cache.get(key)  # Crashes if cache fails!
```

### Retry Logic

```python
# ✅ CORRECT: Retry with exponential backoff
async def query_with_retry(query: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            return await db.query(query)
        except TransientError as e:
            if attempt == max_retries - 1:
                raise
            wait_time = 2 ** attempt
            logger.warning("Query failed, retrying in %s seconds", wait_time)
            await asyncio.sleep(wait_time)
```

## Context Managers

### Use Async Context Managers

```python
# ✅ CORRECT: Async context manager
async def process_file(path: str):
    async with aiofiles.open(path, 'r') as f:
        content = await f.read()
        return process_content(content)

# ❌ WRONG: Sync context manager in async function
async def process_file_wrong(path: str):
    with open(path, 'r') as f:  # Blocks!
        content = f.read()
        return process_content(content)
```

### Create Custom Async Context Managers

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def database_transaction(db):
    """Async context manager for database transactions."""
    await db.begin()
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()

# Usage
async def update_records():
    async with database_transaction(db) as tx:
        await tx.execute("UPDATE ...")
        await tx.execute("INSERT ...")
```

## Performance Optimization

### Batch Operations

```python
# ✅ CORRECT: Batch operations
async def index_files(files: List[str], batch_size: int = 10):
    for i in range(0, len(files), batch_size):
        batch = files[i:i + batch_size]
        tasks = [index_file(f) for f in batch]
        await asyncio.gather(*tasks)

# ❌ WRONG: All at once (may overwhelm system)
async def index_files_wrong(files: List[str]):
    tasks = [index_file(f) for f in files]  # 1000s of tasks!
    await asyncio.gather(*tasks)
```

### Use Semaphores for Resource Control

```python
# ✅ CORRECT: Control resource usage
class ResourceManager:
    def __init__(self, max_concurrent: int = 10):
        self._semaphore = asyncio.Semaphore(max_concurrent)
    
    async def use_resource(self):
        async with self._semaphore:
            # Only max_concurrent operations at once
            return await expensive_operation()
```

### Cache Async Results

```python
from functools import lru_cache

# ✅ CORRECT: Cache expensive operations
@lru_cache(maxsize=1000)
def get_embedding_sync(text: str):
    return embedding_model.encode(text)

async def get_embedding(text: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, get_embedding_sync, text)
```

## Common Pitfalls

### Don't Forget to Await

```python
# ❌ WRONG: Forgot to await
async def process():
    result = async_function()  # Returns coroutine, not result!
    return result

# ✅ CORRECT: Always await
async def process():
    result = await async_function()
    return result
```

### Don't Mix Sync and Async

```python
# ❌ WRONG: Calling async from sync
def sync_function():
    result = async_function()  # Returns coroutine!
    return result

# ✅ CORRECT: Use asyncio.run()
def sync_function():
    result = asyncio.run(async_function())
    return result
```

### Don't Block the Event Loop

```python
# ❌ WRONG: Blocking operation
async def process():
    time.sleep(1)  # Blocks event loop!
    return result

# ✅ CORRECT: Use asyncio.sleep()
async def process():
    await asyncio.sleep(1)  # Non-blocking
    return result
```

## Debugging Async Code

### Enable Async Debug Mode

```python
import asyncio
import logging

# Enable debug mode
asyncio.get_event_loop().set_debug(True)

# Enable asyncio logging
logging.getLogger('asyncio').setLevel(logging.DEBUG)
```

### Detect Slow Callbacks

```python
# Set slow callback threshold
asyncio.get_event_loop().slow_callback_duration = 0.1  # 100ms

# Warnings will be logged for callbacks taking >100ms
```

### Use Async Stack Traces

```python
import traceback

async def debug_function():
    try:
        await risky_operation()
    except Exception:
        # Print full async stack trace
        traceback.print_exc()
        raise
```

## Summary

**Key takeaways:**

1. Use `asyncio.get_running_loop()` in async functions
2. Run CPU-bound operations in executors
3. Use async I/O libraries (aiofiles, aiosqlite, httpx)
4. Control concurrency with semaphores
5. Use condition polling in tests, not fixed sleeps
6. Always await async operations
7. Handle exceptions gracefully
8. Use async context managers
9. Batch operations for better performance
10. Enable debug mode during development

Following these practices ensures your async code is:
- **Correct**: No subtle bugs from wrong event loop
- **Performant**: Non-blocking I/O and proper concurrency
- **Maintainable**: Clear patterns and error handling
- **Testable**: Reliable tests with condition polling
