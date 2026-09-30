# Spec: Retrieval core

Mode: full (changes search behaviour, index contents and chunk boundaries)

- **Status:** Approved
- **Owner:** Sbasha
- **Plan:** [`plan.md`](plan.md)
- **Constrained by:** RFC-0003 (every change is measured by `evals/`), ADR-0002
- **Contract:** none (the `SearchService.hybrid_search` signature is unchanged)

> **Spec contract:** this document defines what "done" means. The implementing
> PR must match this spec, or update it. Verification must be derivable from it.

## Objective

Make `SearchService.hybrid_search` beat independent baselines and Graphify on
the RFC-0003 dev splits by fixing what it indexes and removing the ranking
heuristics that were tuned for a retired backend. Measured before this spec
(SciFact dev, nDCG@10): `inquiry` 0.541 against `bm25` 0.655 and `hybrid` 0.658.

What changes:

1. **Ranking.** Vector and full-text candidates are fused with plain RRF,
   capped per file after fusion, then cut to the limit. These are removed:
   the score pre-filters, max-normalization, overview boosts (and the
   `boost_overview` argument), the IDF content boost with its additive floor,
   the doc-first tie-break, the one-sided fallback pipelines, score-aware and
   weighted RRF with its dual-source bonus, and graph rerank (the
   `rerank_by_graph` argument). The soft `content_preference` stays; callers
   that meant "prefer overview docs" pass `content_preference="PROSE"`.
   Vector search is exhaustive in the configured metric below one million rows.
2. **Chunks.** Code chunks follow syntax boundaries and partition the file.
   Text chunks follow line boundaries. Every chunk's content is exactly its
   `line_start`..`line_end` lines. The whole-file and session-header special
   cases are removed.
3. **Index text.** A chunk is embedded as its project-relative path, its scope
   (enclosing definitions) and its content; `fts_text` holds the same header,
   the raw content and split identifiers.
4. **Embedder.** Chosen by dev-split ablation among models that run locally
   without an API key.

## Boundaries

### Always do
- Measure each change on the dev splits with `python -m evals run
  --baseline <pre-change results>` and keep it only if it improves a primary
  metric (CI excludes 0) or simplifies code without a primary-metric drop
  beyond the dev CI half-width (RFC-0003).
- Keep the knowledge graph's entities and relationships unchanged by chunking.

### Ask first
- Renaming or removing MCP tools or their arguments.

### Never do
- Tune on the test split.
- Special-case a benchmark's file shapes.
- Add a runtime dependency or module boundary without an ADR.

## Testing Strategy

- **TDD** - fusion order, score range, per-file cap, candidate depth; code
  chunk partition; text chunk line truth; index text; graph invariance on
  fixtures.
- **Goal-based check** - `python -m evals run` on the dev splits with
  `--baseline`; results files committed.
- **CLI test** - `ai search` against a real LanceDB fixture prints
  `path:line_start-line_end` and the symbol name.

## Acceptance Criteria

- [ ] AC1 Fused scores lie in [0, 1]: 1.0 means first in both lists, 0.5 means first in one list only. Callers that threshold scores (`find_similar`, gatherer confidence buckets, `detect_ambiguity`) are checked against that scale.
- [ ] AC2 `hybrid_search` retrieves `max(3 * limit, 100)` candidates per retriever, fuses them with RRF (k from `search.hybrid_search.reranker_params.k`), applies `search.deduplication.max_results_per_file` after fusion and returns `min(limit, capped candidates)` results. The removed heuristics in the Objective have no remaining code; their config keys are ignored with a warning rather than rejected, so older configs still load.
- [ ] AC3 Code chunks partition each parsed file (every line in exactly one chunk), stay within the size budget unless one syntax node's single line exceeds it, and break on syntax-node boundaries.
- [ ] AC4 Text chunks hold exactly lines `line_start`..`line_end` and stay within the size budget unless one line exceeds it; the whole-file and session-header special cases are gone.
- [ ] AC5 Graph entity IDs and `(type, source, target)` relationships produced for Python, Java and TypeScript fixtures are identical before and after the chunking change; HTTP-route and DI recognizers still attach.
- [ ] AC6 A chunk's embedded text is its project-relative path, scope and content; `fts_text` holds that header, the raw content and split identifiers.
- [ ] AC7 An index built with an older chunker or embedder is rebuilt by `ai index` (the fingerprint of chunker version and embedder model is part of each file's index state).
- [ ] AC8 `ai search` prints `path:line_start-line_end`, the symbol name and a preview; `path` alone when lines are unknown.
- [ ] AC9 On every dev suite the new `inquiry` beats the pre-spec `inquiry` on the primary metric (paired CI excludes 0), results files committed.
- [ ] AC10 `docs/architecture/search.md`, `AGENTS.md` (tunables), `docs/development/reranker-guide.md` and `docs/mcp/configuration.md` describe the pipeline as built, with no phase history.
