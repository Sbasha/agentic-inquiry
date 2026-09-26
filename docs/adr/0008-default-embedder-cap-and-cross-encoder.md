# ADR-0008: Default to bge-small, three results per file and a fused cross-encoder second stage

- **Status:** Accepted
- **Date:** 2026-09-26
- **Decision-makers:** Sbasha
- **Supersedes:** none
- **Related:** RFC-0003, ADR-0007, `docs/specs/retrieval-core/spec.md`

## Decision summary

- **Decision:** The default embedder is `BAAI/bge-small-en-v1.5`, `search.deduplication.max_results_per_file` is 3, and `search.hybrid_search.rerank_model` is `cross-encoder/ms-marco-MiniLM-L-6-v2` over the fused top 30 in `fuse` mode. The graph channel stays off (`graph_seeds: 0`).
- **Because:** on the RFC-0003 dev splits this combination gave the largest gains on both memory suites, and it stays above BM25 on SciFact, while keeping indexing on a CPU laptop practical.
- **Applies to:** `config/default.yaml`, the matching dataclass defaults in `agentic_inquiry/config.py` and `config/config.schema.json`.
- **Tradeoff accepted:** the cross-encoder adds about 0.9 s (p50, measured on a loaded machine) to each hybrid search and a 90 MB model download on first use. bge-small scores below all-MiniLM-L6-v2 on SciFact.
- **Revisit if:** a local embedder that indexes code repositories at bge-small's speed closes the LongMemEval gap to BGE-m3 dense, or the test-split results contradict the dev ranking below.

## Context

Every figure below is from the RFC-0003 dev split at commit d7492fc or later (the commit that stopped the minified-file check from dropping prose files), with paired comparisons against the pre-change `inquiry` or the baseline arms. Metrics are the pre-registered primaries: unit recall within 2,000 rendered tokens for LOCOMO and LongMemEval, nDCG@10 for SciFact.

| Configuration | LOCOMO | LongMemEval | SciFact |
| --- | --- | --- | --- |
| pre-change `inquiry` (e8b80e5) | 0.459 | 0.505 | 0.541 |
| MiniLM, 1 per file | 0.604 | not run | 0.697 |
| MiniLM, 3 per file | 0.701 | not run | 0.697 |
| MiniLM, 3 per file, cross-encoder | 0.783 | 0.783 | 0.703 |
| bge-small, 3 per file | 0.748 | not run | 0.687 |
| **bge-small, 3 per file, cross-encoder** | **0.809** | **0.794** | **0.679** |
| bge-base, 3 per file | 0.762 | not run | not run |
| bge-small, 3 per file, bge-reranker-base (fuse) | 0.795 | not run | not run |
| bge-small, 3 per file, bge-reranker-base (replace) | 0.805 | not run | not run |
| BM25 baseline | 0.683 | 0.708 | 0.655 |
| BGE-m3 dense baseline | 0.775 | 0.874 | 0.597 |
| hybrid baseline (BM25 + BGE-m3, RRF) | 0.775 | 0.823 | 0.658 |

## Decision drivers

- Retrieval quality on externally labelled data, weighted towards the memory suites, where the gains were largest.
- Index time on a CPU laptop: code repositories run to tens of thousands of chunks, so the embedder must stay small.
- Search latency an agent tolerates (about one second).

## Consequences

- Existing indexes re-embed on the next `ai index`: the file-state salt includes the embedder identity (`watching/file_tracker.py`).
- SciFact nDCG@10 is 0.024 lower than with MiniLM plus the cross-encoder. Against BM25 the dev margin is +0.024, CI [-0.019, +0.068], so the pre-registered non-inferiority hypothesis H2 is at risk on the test split.
- BGE-m3 dense retrieval stays ahead on LongMemEval (0.874 against 0.794). Closing that gap needs a larger embedder: in a dense-only probe on 40 LongMemEval dev cases, bge-small reached 0.798 against BGE-m3's 0.900, and nomic-embed-text-v1.5 embedded about 1.5 turns per second on a loaded CPU, too slow as a default for code repositories.

## Confirmation

- **Mode:** RFC-0003 test-split runs recorded in `evals/results/test-ledger.jsonl`, verdicts from `python -m evals report`.
- **Signal:** H1 to H3.
- **Owner:** Sbasha.

## Alternatives considered

- **all-MiniLM-L6-v2 with the cross-encoder.** Safer on SciFact (+0.048 over BM25, CI [+0.007, +0.091]) but 0.026 lower on LOCOMO and 0.011 lower on LongMemEval.
- **bge-reranker-base as the second stage.** Better unit recall at the top 10 (0.684 against 0.628 on LOCOMO in replace mode) but no better within 2,000 tokens, at about four times the latency.
- **Cross-encoder in replace mode.** On an index built before the minified-file fix, it scored 0.619 on SciFact against 0.657 for fuse mode on the same index; on LOCOMO the two modes were within 0.01.
- **bge-base.** +0.014 on LOCOMO without the cross-encoder, at roughly three times bge-small's embedding cost.
- **A BGE query instruction prefix.** Lowered bge-small dense nDCG@10 on SciFact from 0.697 to 0.684.

## References

- Results files under `evals/results/{locomo,longmemeval,scifact}/`.
