# Query Semantics (QuerySpec)

This document defines the normative semantics for backend-agnostic query execution using `QuerySpec` as described in `docs/design/database-abstraction-revised.md`.

## Scope

Applies to:
- Vector adapter query execution (`execute(spec)` and/or `query(...)`, `vector_search(...)`, `fts_search(...)`, `hybrid_search(...)`)
- Filter semantics (`Filter` AST) as used inside `QuerySpec.filters`
- Cross-project semantics (`QuerySpec.project_ids`)

Out of scope:
- Reranking, deduplication, and boosting (covered in `docs/design/result-contract.md` and `docs/design/database-abstraction-revised.md`)

## QuerySpec (Canonical Fields)

Canonical fields are defined in `docs/design/database-abstraction-revised.md` under “QuerySpec Design”. Implementations may add fields, but must not change the meaning of the canonical ones.

### Invariants

- `table` is a logical table name (see `docs/design/logical-schema-reference.md`).
- `filters` is expressed using the unified `Filter` AST.
- Pagination is stable:
  - `limit` caps returned rows.
  - `offset` skips the first `offset` rows of the *post-filtered, post-sorted* result set.
- Sorting is deterministic when `order_by` is provided. If the backend cannot guarantee deterministic ordering, the adapter must add a secondary stable key (e.g. `id`) when possible.

## Capability-Based Degradation Rules

Adapters may not support all capabilities (FTS, native hybrid, ordering, offsets). The app layer may implement fallbacks, but adapter behavior must be explicit.

### Required behavior

- If a method is called that the adapter does not support, it must raise a clear exception (e.g. `NotImplementedError`) that includes the capability name and the backend name.
- If the app layer requests hybrid behavior (`vector` + `fts_query`) via `execute(spec)`:
  - If the adapter supports native hybrid: it may execute hybrid natively.
  - Otherwise: the adapter must reject the hybrid `execute(spec)` call (do not silently “half execute”); the app layer is responsible for running `vector_search` + `fts_search` and merging via a reranker.

## Project Scoping Semantics

Project isolation is enforced by filtering on `project_id`.

- `filters` may include `project_id` constraints directly.
- If `project_ids` is set:
  - It represents the *allowed project set* for the query.
  - It must be combined with any existing `filters` using logical AND.
  - If `filters` already specifies `project_id`, the intersection semantics apply (AND).
- If both `filters.project_id` and `project_ids` are missing:
  - The query is “cross-project”, and results may include any project.

## Field Selection Semantics

If `select_columns` is provided:
- The adapter should return only those columns when supported.
- If not supported, return full rows and the app layer must ignore extra fields.
- The adapter must always include `id` in the returned rows (even if not in `select_columns`), because it is required for result identity.

## Ordering Semantics

If `order_by` is set:
- The adapter must treat it as a column name in the logical schema for the target table.
- If `order_by` references a column not present in the logical schema, raise a validation error.
- `order_desc` controls direction.

If `order_by` is not set:
- No ordering guarantees are required (unless the backend provides one implicitly).

## Offset Semantics

If the backend cannot apply offsets natively:
- Adapters may emulate offset by fetching `offset + limit` and slicing in memory, but must document the performance implications in adapter documentation.
- If the adapter cannot emulate offset safely (e.g. no stable ordering), it must raise a clear exception.

## Error Semantics

Adapters must:
- Preserve the root cause in the exception chain.
- Include context:
  - backend name
  - table
  - whether vector/fts/filter path was chosen
  - presence of project scoping

## Test Requirements

These semantics must be enforced by tests described in `docs/design/database-abstraction-revised.md` under:
- “Protocol Compliance Tests (Workflow-Based)”
- “Verified Protocol Methods → Actual Call Sites”

