---
name: code-review
description: Code logic and safety review checklist - architecture compliance, async safety, and quality. Auto-loads when reviewing agv code changes.
user-invocable: false
---

# Code Review Checklist

Validate correctness, robustness, quality, and impact of code changes.

## When to Use

- Reviewing PRs
- Self-review before committing
- Auditing existing code

## Review Checklist

### A. Architecture & Standards Compliance

- [ ] **Async-Only:** All I/O functions are `async def`. No blocking calls.
- [ ] **Concrete Types:** Uses concrete classes in type hints, not protocols.
- [ ] **Direct Instantiation:** `Class.from_config(config)`, not custom factories.
- [ ] **Dependency Injection:** Dependencies injected via constructor.
- [ ] **Project Context:** All data operations use `project_id` for isolation.
- [ ] **Central Components:** Uses existing components (SchemaProcessor, EventBus).

### B. Code Design & Quality

- [ ] **God Classes:** Large files (>500 lines) should be split.
- [ ] **Partial Implementations:** No `pass`, `...`, or `NotImplementedError` in non-abstract methods.
- [ ] **Over-Engineering:** No speculative generality (YAGNI).
- [ ] **Dead Code:** No unused imports or unreachable code paths.
- [ ] **Complexity:** No deep nesting (arrow code).

### C. DRY/SRP

- [ ] **Single Responsibility:** Single concern in single component.
- [ ] **DRY Violations:** No duplicated logic that should be shared.
- [ ] **Fallback Patterns:** No cascading `.get()` fallbacks that mask missing data.
- [ ] **Field Name Consistency:** Names match database schema.

### D. Impact Analysis

- [ ] **Signature Compatibility:** No removed arguments or changed return types.
- [ ] **Schema Compatibility:** Database changes are additive or have migration.
- [ ] **Ripple Effects:** Checked usage in dependent modules.
- [ ] **Data Flow Integrity:** Validated against full pipeline (Parser → Indexing → Search).

### E. Async & Concurrency Safety

- [ ] **Concurrency Control:** High-volume operations use `Semaphore` limits.
- [ ] **Error Handling:** `asyncio.gather` uses `return_exceptions=True`.
- [ ] **No Deadlocks:** No nested semaphore acquisition.
- [ ] **Resource Cleanup:** Async context managers for resources.
- [ ] **Cancellation:** Long-running tasks handle `CancelledError`.

### F. Configuration & Environment

- [ ] **Configurability:** No hardcoded constants that should be in config.
- [ ] **Defaults:** New config options have sensible defaults.
- [ ] **Validation:** Config loading validates types and ranges.
- [ ] **Secret Safety:** No secrets in default config. API keys from env only.

### G. Security & Input Validation

- [ ] **Path Traversal:** All file paths validated via `validate_file_path()`.
- [ ] **Query Sanitization:** Search queries sanitized before FTS execution.
- [ ] **ReDoS:** Regex patterns checked for exponential backtracking.
- [ ] **Serialization:** No `pickle` usage on untrusted data.

### H. Simplicity & Maintainability

- [ ] **Brittleness:** Fix is robust, no hard-coded assumptions.
- [ ] **Least Astonishment:** Solution is straightforward, no surprising side effects.
- [ ] **No Magic Numbers:** Hard-coded values are documented or configurable.
- [ ] **Tactical vs Strategic:** Addresses root cause, not just symptom.

## Output Format

```markdown
### Code Review Summary

**Status:** 🟢 Safe | 🟡 Warnings | 🔴 Unsafe

**Architecture Compliance:**
- [✓] Async-only enforcement
- [✓] Project isolation

**Design & Quality:**
- [✓] SRP/God Class check
- [⚠] Implementation completeness - partial impl in X

**Safety Findings:**
1. [Critical] File:Line - Issue description
2. [Warning] File:Line - Issue description

**Recommendations:**
- [Actionable advice]
```
