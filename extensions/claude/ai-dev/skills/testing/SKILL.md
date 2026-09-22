---
name: testing
description: Agentic Inquiry testing guidelines - commands, fixtures, anti-patterns, and condition polling. Auto-loads when writing or running tests.
user-invocable: false
---

# ai Testing Guidelines

Standards for testing Agentic Inquiry code.

## When to Use

- Writing new tests
- Debugging test failures
- Reviewing test coverage

## Quick Reference

| Category | Command | Purpose |
|----------|---------|---------|
| All tests | `uv run --env-file .env pytest` | Full test suite |
| Unit | `uv run --env-file .env pytest -m unit` | Fast, mocked |
| Integration | `uv run --env-file .env pytest -m integration` | Real dependencies |
| Fast feedback | `uv run --env-file .env pytest -m "not slow"` | Exclude slow tests |
| Stop on first | `uv run --env-file .env pytest -x` | Stop on first failure |
| Specific file | `uv run --env-file .env pytest tests/path/test_file.py` | Single file |

## Fixture Naming Convention

| Prefix | Scope | Example |
|--------|-------|---------|
| `mock_*` | Unit tests | `mock_embedding_registry` |
| `integration_*` | Integration tests | `integration_storage` |
| `real_*` | E2E tests | `real_database` |

## Anti-Patterns to Avoid

### Never use `time.sleep()` in async tests

```python
# BAD
await some_operation()
time.sleep(1)  # Blocks event loop!
await check_result()

# GOOD - Use condition polling
def wait_for_condition(condition_fn, timeout=2.0, poll_interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition_fn():
            return True
        time.sleep(poll_interval)
    return False
```

### Never load real embedder in unit tests

```python
# BAD - Slow, requires model download
embedder = SentenceTransformerEmbedder()

# GOOD - Use mock
@pytest.fixture
def mock_embedding_registry():
    with patch('agentic_inquiry.embeddings.registry') as mock:
        mock.get_default.return_value = MockEmbedder()
        yield mock
```

### Never test stdlib/third-party code

```python
# BAD - Testing json.loads behavior
def test_json_loads():
    result = json.loads('{"a": 1}')
    assert result == {"a": 1}

# GOOD - Test YOUR logic using json
def test_config_parsing():
    config = MyConfig.from_json('{"name": "test"}')
    assert config.name == "test"
```

## Test Organization

```
tests/
├── unit/           # Fast, mocked tests
├── integration/    # Real dependencies
├── e2e/            # Full system tests
├── fixtures/       # Shared fixtures
└── conftest.py     # Pytest configuration
```

## Full Documentation

See the **Testing** section of [CONTRIBUTING.md](../../../../../CONTRIBUTING.md) for:
- Testing philosophy
- Directory structure details
- Fixture conventions
- Test categories and markers
