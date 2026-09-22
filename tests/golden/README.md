# Golden Bench

Pre-flight safety net for the audit's deletion clusters
(see [#156](https://github.com/sbasha/agent-vault/issues/156)
and [docs/rfc/0001-golden-bench.md](../../docs/rfc/0001-golden-bench.md)).

`make bench` indexes a fixed slice of this repo into a temp LanceDB
project, runs the 15 queries in `queries.json`, and fails the build if
**recall@10** drops or **p95 search latency** exceeds the pinned
baseline by more than 20%.

## Run

```bash
make bench         # diff against tests/golden/baseline.json (CI-safe)
make bench-pin     # regenerate the baseline (deliberate, never auto)
make bench-clean   # drop the cached corpus + index
```

## What lives here

- `queries.json` — 15 queries with `expected_contains` term lists.
- `baseline.json` — pinned recall@10 + latency at the last `bench-pin` (committed).
- `bench.py` — canonical entry point. `python tests/golden/bench.py --help`.
- `test_search_quality.py` — thin pytest wrapper (slow, marked `golden`).

Bench artifacts (corpus mirror + LanceDB index + last results) live at
`$TMPDIR/agv-golden-bench/` — outside the repo so the indexer's
`.gitignore` walk doesn't exclude them. `make bench-clean` wipes that path.

## When to re-pin

Re-pin (`make bench-pin`) only on a deliberate, explainable change:

- The corpus subdirs in `bench.CORPUS_SUBDIRS` shifted.
- The query set in `queries.json` changed.
- A search-pipeline change that improved (or measurably justified) the numbers.
- Hardware changed (CI moved, you switched machines and the team agrees the
  new floor is the new floor).

**Do not re-pin to make the bench green after a regression.** That's the
opposite of what the gate exists for. Investigate first.

## Metric notes

- **recall@10** = mean across queries of (`expected_contains` terms found
  in top-10 result content) / (total expected terms). Term presence, not
  labelled doc-IDs — catches gross retrieval regressions, will miss
  ranking-order regressions that preserve the term set. Upgrade path
  in the RFC.
- **Latency** = wall-clock around `SearchService.hybrid_search()`,
  embedding excluded. Each query runs `LATENCY_ITERATIONS=5` times and
  we keep the min to strip GC/scheduler noise. Median + p95 reported
  across the per-query mins.
- **Backend** = LanceDB only. Cross-backend parity is its own concern.
