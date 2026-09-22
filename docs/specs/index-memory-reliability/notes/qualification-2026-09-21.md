# Qualification record, 2026-09-21

Evidence for AC 15-17 of [`../spec.md`](../spec.md). Full receipts
(command, exit code, wall-clock, stdout/stderr SHA-256, reported summary,
error-class tallies) live under
`~/.agv/qualification/index-durability-20260921/receipts/`; the corpus,
the indexes, and the logs stay there too. This page carries only counts
and hashes.

Setup: branch code installed into an isolated venv with lancedb 0.38.0
(the version `uv tool install .` resolves), `AGV_EMBEDDING_DEVICE=cpu`,
`--skip-onboard-check`, one 1,443-file repository as corpus (1,437 files
indexable), project id fixed across runs.

## Receipts

| Receipt | What ran | Exit | Wall | Result |
|---|---|---|---|---|
| `00-real-partial-index-inspect` | read-only inspector on the failed run's index | - | - | document_chunks 20,684 rows, graph_entities 20,880, graph_relationships 7,099 rows / 6,901 distinct keys (198 duplicate-key rows); vector index only on every table; 1,394 files indexed of 1,443 |
| `01-repro-head-f936def-lancedb038` | branch HEAD `f936def` (per-write `optimize()`), corpus into a clone of that index | 0 | 6,235 s | 1,437 processed, 0 failed, 122 `Retryable commit conflict` retries (CreateIndex vs CreateIndex 91, CreateIndex vs Rewrite 15, Rewrite vs Rewrite 13, Rewrite vs Update 2, Rewrite vs CreateIndex 1); 13.8 files/min |
| `05-tests-database-lancedb038` | `tests/database` under lancedb 0.38.0 | 0 | - | 536 passed, 0 failed |
| `30-fresh-index-fixed-lancedb038` | fixed code, corpus into an empty environment | 0 | 321 s | 1,437 processed, 0 failed, 0 retries, error.log empty; 268 files/min; 34,327 chunk rows / 34,784 entity rows / 59,536 relationship rows, 0 duplicate keys in every table; FTS index on `fts_text` present |
| `11-fresh-process-status-fresh30` | fresh process `agv index status` on that index | 0 | 2.6 s | 34,327 / 34,784 / 59,536, equal to the on-disk row counts |
| `12-fresh-process-search-fresh30` | fresh process `agv search --json` (hybrid) | 0 | 6.8 s | 3 results, every `file_path` exists in the corpus |
| `40-search-to-source-journey` | provenance check on those 3 results | - | - | CODE result: `line_start`/`line_end` 1381-1475 contain the returned element and first content line; file SHA-256 recorded. PROSE results: `line_start=-1`, file-level provenance plus whitespace-normalized text match (one full match, one first-12-words match) |
| `10-recover-real-partial-index-fixed` | fixed code, corpus into a second clone of the failed run's index (20,684 / 20,880 / 7,099 rows before) | 0 | 477 s | 1,437 processed, 0 failed, 0 retries, error.log empty; native FTS index created on the existing table; after: chunks 34,328 distinct (0 dup), entities 34,789 (0 dup), relationships 59,548 distinct with the 198 legacy duplicate rows unchanged |
| `20-second-run-same-index` | fixed code again over the recovered index | 0 | 373 s | 1,437 processed, 0 failed, 0 retries; chunks 34,328 and entities 34,789 distinct keys unchanged; duplicate rows 0 / 0 / 198 unchanged; relationships grew 59,548 to 66,813 distinct keys (unresolved targets 296 to 4,016; graph-builder behavior, see backlog) |
| `21-interrupted-run` | fixed code, empty environment, SIGTERM after 158 files | -15 | 52 s | 662 chunk rows, 13,371 entity rows, 0 duplicates, no relationships table yet (batch flush had not run) |
| `22-rerun-after-interrupt` | full re-run in that environment | 0 | 327 s | 1,437 processed, 0 failed, 0 retries; chunks 34,327 and entities 34,784 distinct keys equal to `30-*`; relationships 59,537 (`30-*`: 59,536); 0 duplicates in every table |

## What qualified

- AC 15: recovery of the real partial index exits 0 with zero
  write-conflict classes and zero failed files (`10-*`); the fresh run
  indexes at 268 files/min against a bound of 32 (`30-*`); fresh-process
  status and search read the index (`11-*`, `12-*`).
- AC 16: re-run over the same index leaves chunk and entity keys
  unchanged and grows no duplicate rows (`20-*`); an interrupted run
  followed by a full re-run reaches the same chunk and entity key counts
  as the uninterrupted run (`21-*`, `22-*`).
- AC 17: one hybrid query to a code chunk with file, line range, element
  name, and file hash verified against the corpus (`40-*`).
- Storage tests pass on lancedb 0.38.0 (`05-*`: 536 passed).

## What did not, or only partly

- PROSE chunks from the document parser carry no line range; their
  provenance is file plus normalized text.
- The recovered index (`10-*`) keeps the 198 duplicate-key relationship
  rows the unserialized writer left; the fixed code adds none and the
  fresh index has none. Repair is an `Ask first` item in
  `docs/backlog.md`.
- Re-runs re-parse every file (no unchanged-file skip); idempotent, not
  incremental.
- A re-run over a complete index adds `calls` and `imports` relationship
  keys whose targets match no stored entity (`20-*`); the write layer
  stores each once, the graph builder's resolution is the open item in
  `docs/backlog.md`. The comparator candidate is `30-*` (single run,
  59,536 relationships, 296 unresolved targets), not the twice-run
  index.
