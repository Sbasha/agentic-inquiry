---
name: coding-guidelines
description: Agent-Vault coding standards - parser constraints, logging, types, security, and async patterns. Auto-loads when writing or reviewing agv code.
user-invocable: false
---

# agv Coding Guidelines

Standards for contributing to Agent-Vault.

## When to Use

- Writing new code for agv
- Reviewing PRs
- Debugging parser or async issues

## Parser Metadata Constraints

**CRITICAL:** The `metadata` dict in `ParserChunk` has strict LanceDB schema constraints:

| Allowed | Not Allowed |
|---------|-------------|
| `str`, `int`, `float`, `bool`, `None` | `list`, `dict`, complex objects |

- Use `symbols` field (NOT `code_symbols`)
- Store metrics in `ranking_signals`, complex data in `symbol_metadata`
- See `docs/development/parser-guidelines.md` for full details

## Required: Lazy Logging

```python
# BAD - eager string interpolation
logger.info(f"Processing {count} items")

# GOOD - lazy formatting
logger.info("Processing %s items", count)
```

## Required: Complete Type Hints

All functions must have type hints. Use concrete classes, not protocols.

```bash
uv run --env-file .env mypy agent_vault/
```

## Required: Security Practices

**Path validation** (prevent directory traversal):
```python
from agent_vault.mcp.utils.validation import validate_file_path
validated_path = validate_file_path(file_path, project_root)
```

**API key comparison** (prevent timing attacks):
```python
secrets.compare_digest(provided, expected)
```

## Async Patterns

**Semaphore for concurrency control:**
```python
semaphore = asyncio.Semaphore(10)
async with semaphore:
    await process_document(doc)
```

**Gather for parallel execution:**
```python
results = await asyncio.gather(*[process(item) for item in items])
```

**Never use blocking calls:**
```python
# BAD
time.sleep(1)

# GOOD
await asyncio.sleep(1)
```

## Memory System Usage

```python
from agent_vault.memory import MemorySystem
from agent_vault.embeddings import EmbeddingService
from agent_vault.config import Config

config = Config.load()
embedding_service = EmbeddingService(config)
memory_system = MemorySystem(config, embedding_service)
await memory_system.initialize()

# Store with automatic tier selection
item = await memory_system.store(
    content="Important insight",
    context=context,
    importance=0.9  # High = semantic tier
)

# Retrieve with adaptive strategy
results = await memory_system.retrieve(
    query="query",
    context=context,
    strategy="adaptive",
    limit=10
)
```

## Search Service Usage

```python
from agent_vault.search import SearchService
from agent_vault.storage.facade import StorageFacade

storage = await StorageFacade.from_config(config, project_id)
search = SearchService(storage, config)

# Hybrid search
results = await search.hybrid_search(
    query_vector=query_vector,
    query_fts="authentication",
    limit=10,
    rerank_by_graph=True
)
```

## Metrics and Correlation

```python
from agent_vault.metrics import get_metrics_tracker
from agent_vault.correlation import correlation_context

metrics = get_metrics_tracker()

with metrics.track_latency("operation"):
    result = await some_async_operation()

with correlation_context() as corr_id:
    logger.info("Request", extra={"correlation_id": corr_id})
```
