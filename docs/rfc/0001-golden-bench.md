---
rfc: 0001
title: "Golden bench: pin recall@10 + latency before deletion clusters land"
status: accepted
authors: [eu-gene-lim]
created: 2026-04-29
related: ["#156", "PLAN.md Cluster 0"]
---

## Summary

Establish a runnable golden bench (`make bench`) that pins `recall@10` and
median + p95 search latency to `tests/golden/baseline.json`, so the audit's
deletion clusters can't silently regress search quality. Indexes a fixed,
in-tree corpus into a temp LanceDB project, runs the existing 15 queries
from `tests/golden/queries.json`, and exits non-zero on regression.

## Motivation

The audit (`~/Documents/agentic-inquiry-audit/PLAN.md`) plans 11 clusters of
deletion across ~25K LOC. The README's "10/10 across keyword, conceptual,
structural queries" claim isn't a measurement — it's marketing copy.
Without a numerical floor, every cluster ships on faith that nobody
broke recall.

The existing `tests/golden/test_search_quality.py` is `pytest.mark.skip`'d
because the API expects pre-computed embeddings (`query_vector`,
`query_fts`) rather than a query string, and the fixtures point at a
`golden_dataset/` directory that doesn't exist. So the safety net was
never live.

## Design

### Corpus

The repo itself, restricted to the subdirs that ground each query in
`queries.json`. The first iteration used a 6-subdir slice and was
non-deterministic at the per-query level: queries whose key tokens (e.g.
`mcp`) didn't appear in the corpus drew near-random vector results, and
aggregate recall@10 flipped between 0.9 and 0.97 across runs. The
current list is the minimum that keeps every query reproducibly
grounded:

```python
CORPUS_SUBDIRS = [
    "search", "storage", "embeddings", "parsers", "indexing", "memory",
    "mcp", "watching", "cache", "events", "metrics", "connectors", "cli",
]
```

Mirrored (via copy, not symlink) into a single staging directory at
`$TMPDIR/ai-golden-bench/corpus/` so the pipeline runs once. The
implementation discovered that symlinking each subdir made the indexer
treat the symlink as a single unparseable file; copying is the
correct shape. Stable across clones; re-pin baseline whenever the
corpus subdirs gain or lose mass.

### Metric

Per-query recall = fraction of `expected_contains` terms found in the
top-10 result content. Aggregate `recall@10` = mean across queries.
Acknowledged limitation: `expected_contains` is term-presence, not
labelled doc-IDs. A drop of >0 is still a real signal that retrieval
got worse; the metric just won't catch ranking-order regressions that
preserve the term set. Upgrade path: if a cluster's review surfaces a
ranking regression this metric misses, swap to
`(query_id, expected_chunk_ids)` tuples and recompute recall over IDs.

### Latency

Wall-clock around `SearchService.hybrid_search()` only. Embedding is
called once before the loop as a warmup so the first query isn't an
outlier. Median + p95 across queries.

### Tolerances

- Recall: must equal-or-exceed baseline. Any drop is a fail.
- Latency: p95 may not exceed `baseline_p95 × 1.20`. The 20% slack is
  to absorb noise on shared-CI hardware without paving over real
  regressions; it's a knob (`LATENCY_REGRESSION_TOLERANCE`) and can
  tighten as the bench environment stabilises.

### Storage backend

LanceDB only. Postgres / AlloyDB / CloudSQL all use the same
`HybridSearchService`; the safety net for cluster work is at the
search-pipeline layer, not the storage layer. Cross-backend
parity is out of scope here and worth its own RFC.

### Files

```
tests/golden/
├── bench.py                    # canonical entry; supports --pin / --reindex / --json
├── baseline.json               # pinned baseline (committed)
├── queries.json                # existing 15 queries (unchanged)
├── test_search_quality.py      # thin pytest wrapper around bench.py
└── conftest.py                 # legacy fixtures, kept for now
Makefile                        # bench / bench-pin / bench-clean
scripts/bench/repro_happy_paths.sh   # task 0.3
$TMPDIR/ai-golden-bench/       # bench artifacts (corpus, index, results)
```

### Modes

```
make bench         # diff against baseline.json, exit 1 on regression
make bench-pin     # regenerate baseline.json (deliberate, never auto)
make bench-clean   # rm -rf $TMPDIR/ai-golden-bench
```

`bench.py --json` for CI integration.

### Isolation

Bench overrides `AI_STORAGE_ROOT`, `AI_STORAGE_DEFAULT_PROJECT_ID`,
`AI_STORAGE_BACKEND` via env vars so the run can't read or write the
user's `.agentic-inquiry/` or any project-root `agentic-inquiry.yaml`. All bench
artifacts (staged corpus, LanceDB index, last results) live under
`$TMPDIR/ai-golden-bench/` — outside the repo because the indexer
applies the project's `.gitignore`, and a repo-local `.benchmarks/`
path matches the gitignore rule and gets silently excluded.

## Alternatives considered

- **Use a checked-in micro-corpus.** Rejected: another fixture to
  maintain, drifts from real query patterns. Indexing the repo
  dogfoods and stays representative.
- **Use the CLI (`ai search ...`) and parse stdout.** Rejected: harder
  to extract numbers reliably, slower (process-spawn per query),
  couples the bench to CLI output formatting.
- **Run on every backend (LanceDB + Postgres + AlloyDB).** Rejected for
  scope. Cluster 0 is half a day; multi-backend bench is its own
  cluster. Filed as follow-up if the search pipeline starts diverging
  per backend.
- **`expected_chunk_ids` instead of `expected_contains`.** Rejected for
  scope — would require labelling all 15 queries against the corpus.
  Documented as the upgrade path above.

## Risks

- **Embedding model download on cold cache.** First `make bench` after
  `uv sync` downloads ~80MB for `all-MiniLM-L6-v2`. Acceptable; runs
  cached afterwards.
- **Corpus drift across commits.** If someone refactors a corpus
  subdir, recall@10 may move without any search-pipeline change.
  Mitigation: re-pin via `make bench-pin` is explicit, and the
  baseline records git SHA so unexpected drift is detectable.
- **Per-machine latency variance.** Local laptop p95 will differ
  from CI. The 20% tolerance absorbs this; if CI noise is wider,
  lift the knob or add a `--latency-tolerance` flag.

## Ship gate

Per issue #156: a fresh `uv sync && make bench` reproduces the
committed baseline (zero failed queries, p95 within budget). The
ship gate for downstream clusters is `make bench` green after
their changes land.
