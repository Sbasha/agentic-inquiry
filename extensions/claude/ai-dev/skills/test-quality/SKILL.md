---
name: test-quality
description: Unit test quality review - anti-patterns, assertion quality, and meaningful test design. Auto-loads when writing or reviewing unit tests.
user-invocable: false
---

# Unit Test Quality Review

Identify tests that inflate coverage without providing confidence.

## When to Use

- Reviewing test quality
- Writing new tests
- Fixing flaky or weak tests

## Core Question

**"If someone breaks this behavior, will this test catch it?"**

If the answer is "no" or "maybe," the test needs work.

## Anti-Pattern Catalog

### 1. Existence/Truthiness Tests
```python
# BAD
assert result is not None
assert response
assert len(items) > 0
```
**Problem:** Passes for almost any non-empty return value.

### 2. Tautological Tests (Testing the Mock)
```python
# BAD
mock_service.get_user.return_value = {"name": "Alice"}
result = mock_service.get_user(123)
assert result["name"] == "Alice"  # Testing unittest.mock, not your code
```

### 3. Implementation Mirroring
```python
# BAD - duplicates implementation logic
expected = sum(item.price * item.qty for item in items)
assert calculate_total(items) == expected

# GOOD - independently calculated
assert calculate_total(items) == 35
```

### 4. Happy Path Only
Missing: None, empty strings, malformed inputs, boundary conditions, error paths.

### 5. Over-Mocking
```python
# BAD - 5+ patches means you're testing glue code
@patch('module.database')
@patch('module.cache')
@patch('module.logger')
@patch('module.validator')
@patch('module.notifier')
def test_process(...):
```

### 6. Assert-Free Tests
```python
# BAD - passes if no exception
def test_process_data():
    result = process(data)
    # No assertion!
```

### 7. Stringly-Typed Assertions
```python
# BAD - tests copy, not behavior
assert "successfully" in response.message
```

### 8. Testing Framework/Library Code
```python
# BAD - testing json.loads, not your code
assert json.loads(json.dumps(data)) == data
```

### 9. Assertion Roulette
Multiple unrelated assertions in sequence. First failure hides others.

### 10. Testing Private Implementation
```python
# BAD - breaks on refactor
assert service._cache["data"]["_processed_at"] is not None
```

### 11. Redundant Assertions
```python
# BAD - the specific assertion implies all the general ones
assert result is not None
assert isinstance(result, str)
assert len(result) > 0
assert result == "Alice"  # This alone is sufficient
```

### 12. Magic Number Assertions
```python
# BAD - unclear if 7 is a requirement or just what happened
assert len(results) == 7

# GOOD - derives from test setup
assert len(results) == len(input_items)
```

## Good Test Properties

1. **Specifies behavior** - Name documents what code should do
2. **Fails when behavior breaks** - Catches regressions
3. **Tests one logical concept** - Easy to diagnose failures
4. **Uses realistic inputs** - Resembles production
5. **Has clear expected values** - "Why" is obvious
6. **Is independent** - No test order dependencies

## Review Questions

- If this code had a bug, would this test catch it?
- Could this test pass even if the code is wrong?
- Is this testing MY code or a library I depend on?
