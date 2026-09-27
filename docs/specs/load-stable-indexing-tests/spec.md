# Spec: Indexing tests that hold under CPU load

Mode: light (no risk trigger fired)

- **Status:** Shipped (2026-09-27)

## Objective

Two indexing tests fail when the machine is busy and pass in isolation. With
56 busy-loop processes on a 16-core Mac (load average 70-95),
`test_chunk_relationships_called_once_per_chunk` raised Hypothesis
`DeadlineExceeded` (235-328 ms against the 200 ms default) in 5 of 5 runs, and
`test_property_3_cache_miss_performance_bound` failed "Cache miss took N ms,
limit is 100ms" (113-346 ms) in 17 of 25 runs. The same load produced one
`DeadlineExceeded` in `test_property_5_profiling_data_completeness`. The first
and last assert call counts, so a deadline adds nothing. The second measures
wall-clock time, which depends on the scheduler, not on the resolver.

What the resolver tests protect is the cost model of the cache: a hit does no
backend work, and a miss walks the strategy chain once and caches the result,
so the repeat is a hit.
Assert that directly, and drop every wall-clock bound in
`tests/indexing/test_resolve_import_performance.py`.

## Acceptance Criteria

- [x] `test_chunk_relationships_called_once_per_chunk` and every Hypothesis test
  in `test_resolve_import_performance.py` run with `deadline=None`.
- [x] A cache hit, of a resolved or an unresolved (None) result, calls no method
  on the database or symbol registry, for any generated target name, type and
  source file.
- [x] An unresolved miss without an import path issues each of `query_raw`,
  `query_entities`, `lookup_by_name` and `lookup_by_name_and_type` exactly once,
  and repeating the same call is a cache hit that issues none. A miss with an
  import path, or one the symbol strategy resolves, issues more calls; those
  paths are not pinned here.
- [x] `SimpleCache` tests assert stored results and least-recently-used eviction
  instead of lookup latency.
- [x] No test in either file reads the clock.
- [x] Both files pass repeated runs under the load that reproduced the failures:
  the resolver file 25 of 25 and the counting test 24 of 24, at load average
  70-136.
- [x] The new hit and miss assertions fail when the resolver skips the cache
  lookup or the cache write.

## Boundaries

Resolver production code is unchanged. Other Hypothesis tests keep the default
deadline; a repo-wide Hypothesis profile is a separate decision.

## Tasks

1. Set `deadline=None` on the relationship counting property test.
2. Replace the timing assertions in `test_resolve_import_performance.py` with
   backend-call and cache-behavior assertions.

## Testing Strategy

Goal-based: run both files 25 times with 56 busy-loop processes on the 16-core
machine, mutate the resolver to bypass the cache read or write and confirm the
new tests fail, and diff the failing-test set of `tests/indexing` against the
base commit with identical flags.
