# Plan: Retrieval core

## Approach

The work proceeds in order of expected effect on the RFC-0003 dev metrics:
ranking first (it is cheapest to change and removes confounds), then text
chunks, then code chunks and index text, then the embedder, then the output
surface. Each task lands with a dev-split results file so its delta is on
record. The graph retrieval channel is a separate follow-up spec, because it
depends on stable chunk identities from this one.

## Constraints

- The `SearchService.hybrid_search` signature stays. Callers that pass
  `boost_overview`, `content_preference` or `rerank_by_graph` keep working;
  those arguments stop changing the ranking and are removed from callers in
  the same PR.
- LanceDB native FTS (stemming and stop words on) remains the lexical engine.

## Construction tests

- `tests/search/test_hybrid_core.py`: RRF over both lists, one empty list,
  per-file cap after fusion, limit applied last, no score clamping.
- `tests/parsers/test_text_chunks.py`: line mapping, size bound, no overlap,
  long single line.
- `tests/parsers/test_code_chunks.py`: partition property on Python, Java and
  TypeScript samples; size bound; scope names.
- `tests/indexing/test_index_text.py`: embedded text and `fts_text` shape.

## Tasks

### T1: Ranking
Depends on: none
Mode: TDD
Files: `agentic_inquiry/search/hybrid_search.py`, `agentic_inquiry/search/rerankers/rrf.py`, `agentic_inquiry/storage/providers/lancedb/vector.py`, `config/default.yaml`, `agentic_inquiry/config.py`
Done when: construction tests pass and a SciFact, LOCOMO and SWE-bench dev run is recorded.

### T2: Text chunks
Depends on: T1
Mode: TDD
Files: `agentic_inquiry/parsers/implementations/fallback_text.py`, `config/default.yaml`

### T3: Code chunks and index text
Depends on: T1
Mode: TDD
Files: `agentic_inquiry/parsers/implementations/unified_code.py`, `agentic_inquiry/indexing/document_processor.py`

### T4: Embedder
Depends on: T2, T3
Mode: goal-based (dev-split ablation, results committed)

### T5: Output surface
Depends on: T1
Mode: manual QA
Files: `agentic_inquiry/cli/search.py`

### T6: Architecture doc
Depends on: T1 to T5
Mode: goal-based. Done when: `docs/architecture/search.md` has no phase history and names the fusion, cap and chunking as built.

## Risks

- Index time grows with a larger embedder; index seconds are part of every results file.
- Removing the one-sided fallbacks changes behaviour on empty FTS results; RRF over one list reduces to that list's order, which is the intended behaviour.
