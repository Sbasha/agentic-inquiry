# Spec: Memory tests match the memory package's real layout and config

Mode: light (no risk trigger fired)

- **Status:** Shipped (2026-09-26)
- **Constrained by:** none

## Objective

Thirteen tests in `tests/memory` fail deterministically because they assert
against module paths and a config shape the memory package has never had,
here or in the upstream Agent Vault history it was imported from. The product
code is the source of truth: the memory tiers live in `agentic_inquiry.memory.layers`
(`working`, `episodic`, `semantic`), and `RetrievalEngine` reads
`config.embeddings.default_dimensions` to validate query embeddings. The
tests must exercise that real surface so a failure means a behavior
regression, not a stale import or a hand-built config that omits fields.

## Acceptance Criteria

- [x] `test_memory_system_initialization` imports the tier classes from
  `agentic_inquiry.memory.layers` and passes.
- [x] The retrieval-engine tests build a real `Config` (a dataclass whose
  fields a `MagicMock(spec=Config)` hides) with the test's `RetrievalConfig`,
  instead of a spec'd mock that lists only the attributes the test author
  expected the engine to read. All twelve named tests pass.
- [x] No `tests/memory` test builds `MagicMock(spec=Config)`; the
  `MemorySystem` tests that passed with one keep passing with a real `Config`.
- [x] With `INQUIRY_EMBEDDING_DEVICE=cpu uv run pytest -p no:randomly -q
  tests/memory`, the failing-test set on this branch is the origin/main
  failing set minus these thirteen, with no additions (K-0001 set diff).
- [x] No product code changes.

## Boundaries

Out of scope: `TestCompleteMemoryLifecycle::test_store_retrieve_update_delete`
in `tests/memory/test_e2e_workflows.py`, which fails nondeterministically on
origin/main. Its cause is a product race (a detached access-stat write in
the episodic layer overwrites `update_importance`), not test drift, and it
needs its own change: see
[`backlog.md#memory-test-drift`](../../backlog.md#memory-test-drift).

## Tasks

1. Point the `test_memory_system_initialization` imports at
   `agentic_inquiry.memory.layers`. Verification: goal-based (the test passes).
2. Replace every `MagicMock(spec=Config)` in `tests/memory` with a real
   `Config` built from the same sub-configs: two sites in
   `test_retrieval_engine.py`, four in `test_memory_system.py`.
   Verification: goal-based (the twelve retrieval tests pass; the
   `MemorySystem` tests stay green).
3. Diff failing-test sets against origin/main per K-0001.
