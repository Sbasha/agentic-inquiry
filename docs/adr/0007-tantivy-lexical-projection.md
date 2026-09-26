# ADR-0007: Full-text ranking uses a Tantivy BM25 projection of the chunk table

- **Status:** Accepted
- **Date:** 2026-09-26
- **Decision-makers:** Sbasha
- **Supersedes:** none
- **Related:** RFC-0003, ADR-0006, `docs/specs/retrieval-core/spec.md`

## Decision summary

- **Decision:** We will rank full-text candidates with a Tantivy BM25 index, stored beside the local LanceDB database and rebuilt from the `fts_text` column whenever the table version changes. LanceDB's native FTS remains only as the fallback for a non-local database URI.
- **Because:** on the RFC-0003 SciFact dev split, LanceDB 0.25 native FTS scored nDCG@10 0.20 to 0.40 across its tokenizer options, while Tantivy BM25 over the same text scored 0.59, and the hybrid pipeline's quality is bounded by its lexical channel.
- **Applies to:** `agentic_inquiry/database/lexical.py`, `LanceDBQueryBuilder.fts_search`.
- **Tradeoff accepted:** the first search after the table changes rebuilds the projection. That takes seconds at 10^5 rows.
- **Revisit if:** LanceDB's native FTS matches Tantivy on the RFC-0003 lexical metrics, or a table grows large enough that a full rebuild on change is too slow and incremental updates are needed.

## Context

The hybrid pipeline fuses a vector list with a full-text list. The full-text list comes from `table.search(query, query_type="fts")`. On SciFact dev, measured on the same rows:

| Engine | nDCG@10 |
| --- | --- |
| LanceDB native FTS, defaults (stemming, stop words) | 0.20 |
| LanceDB native FTS, no stemming, no stop words | 0.40 |
| `bm25s` over `fts_text` | 0.58 |
| LanceDB legacy Tantivy FTS | 0.60 |
| Tantivy BM25 (`tantivy` package, `en_stem`) | 0.59 |

The earlier pipeline hid this with an IDF-weighted content boost and an additive floor, which the retrieval-core spec removes. `tantivy` was already a runtime dependency with no callers.

## Decision

- The projection holds `id` (raw, stored) and `text` (`en_stem` analyzer) for every row of the table.
- `meta.json` records the table version, the row count, the column and the index format. On a mismatch the projection is rebuilt in a staging directory under a file lock and swapped in with a rename.
- A query is lower-cased word terms joined as an OR query. Rows are read back from LanceDB by `id` with the caller's filter, over-fetching four candidates per requested row.

## Decision drivers

- Retrieval quality measured on externally labelled data.
- No new dependency.
- One source of truth: the projection can be deleted and rebuilt from the table.

## Consequences

- Full-text quality no longer depends on LanceDB's FTS implementation.
- The FTS index LanceDB still builds on `fts_text` is unused for local databases. Removing its creation is a follow-up once no path depends on it.

## Confirmation

- **Mode:** lint/CI.
- **Signal:** `tests/database/test_lexical.py`, plus the RFC-0003 dev results for `inquiry`.
- **Owner:** Sbasha.

## Alternatives considered

- **LanceDB legacy Tantivy FTS (`use_tantivy=True`).** Same quality, but it is a deprecated path that newer LanceDB versions refuse alongside native indexes.
- **`bm25s` as a runtime dependency.** Needs a new dependency and an ADR, with no quality gain over Tantivy.
- **Tune LanceDB native FTS.** It peaked at 0.40.

## References

- RFC-0003 results under `evals/results/scifact/`.
