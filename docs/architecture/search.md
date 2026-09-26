---
title: "Search Architecture"
tier: 3
audience: developer
journey: ["extension-developer"]
related: ["overview.md", "knowledge-graph.md", "../../evals/README.md"]
last_updated: 2026-09-26
---

# Search Architecture

How a query becomes ranked results: what the index holds, how the two
retrievers are fused, and what an agent receives. Retrieval quality is measured
by the evaluation harness in [`evals/`](../../evals/README.md)
([RFC-0003](../rfc/0003-eval-harness-and-competitor-parity.md)), not asserted
here.

## What is indexed

The parser chain turns each file into chunks, and every chunk is stored as one
row of `document_chunks` in LanceDB.

| File kind | Parser | Chunk boundaries | Line numbers |
| --- | --- | --- | --- |
| Source code with a tree-sitter grammar | `unified_code`, then `parsers/code_chunks.py` | Definitions (functions, methods, classes): the file is split top-down until each piece fits `parsers.unified_code.max_chunk_chars` (1,500), then small neighbours merge | Exact; chunks partition the file |
| Markdown and plain text | `fallback_text` | Lines, packed up to `parsers.fallback_text.max_chunk_size` (1,000) characters, breaking after blank lines | Exact |
| PDF, Office, HTML, XML, reStructuredText | `document` (unstructured) | Document elements | Unknown for most formats |
| Binary files | none | Skipped: a NUL byte or over 5% control characters in the first megabyte | |

Code parsing also extracts graph entities and `calls`, `imports`, `inherits`
and `defines` relationships. Those move from the parser's grouping chunks onto
the partition chunk holding each definition, so chunk boundaries do not change
the graph (see [knowledge-graph.md](knowledge-graph.md)).

Each row carries two texts, built in `indexing/document_processor.py`:

- **Embedded text:** the project-relative path, the scope (enclosing
  definitions, or the Markdown heading path) and the chunk content.
- **`fts_text`:** the same header and content, plus the words inside camelCase
  identifiers. The BM25 tokenizer already splits `snake_case` on the underscore.

File-state hashes carry a salt of the index format and the configured
embedding model (`watching/file_tracker.py`), so changing the chunker, the
index text or the embedder makes the next `ai index` rebuild every file.

## How a query is ranked

`SearchService.hybrid_search` delegates to `HybridSearchService.hybrid_search`
(`search/hybrid_search.py`):

1. **Candidates.** The vector and full-text retrievers each return
   `max(3 × limit, 100)` candidates.
   - **Vector:** exhaustive cosine search below one million rows
     (`database/query_builder.py`).
   - **Full text:** BM25 from a Tantivy projection of `fts_text`
     (`database/lexical.py`,
     [ADR-0007](../adr/0007-tantivy-lexical-projection.md)), rebuilt whenever
     the table version changes.
2. **Fusion.** Reciprocal rank fusion with k from
   `search.hybrid_search.reranker_params.k` (60). Scores are divided by the
   best achievable fused score, so 1.0 means first in both lists and 0.5 means
   first in one list only.
3. **Graph channel** (optional, `search.hybrid_search.graph_seeds`, 0 = off).
   The definitions inside the top N fused results seed a one-hop walk over
   `calls` and `inherits` edges (`search/graph_channel.py`). The chunks holding
   the neighbouring definitions form a third list, and the three lists are
   fused again.
4. **Cross-encoder second stage** (optional,
   `search.hybrid_search.rerank_model`, empty = off). The cross-encoder scores
   the top `rerank_top_n` results against the query. In `fuse` mode its order
   is fused by RRF with the fused order; in `replace` mode its order stands
   alone. Scores keep the fused scale.
5. **Content preference** (optional). Results of the preferred content type
   get their score raised by the given weight and the list re-sorts, without
   excluding anything.
6. **Per-file cap.** `search.deduplication.max_results_per_file` results per
   file, applied to the fused order.
7. **Limit**, applied last.

Other rerankers (`linear_combination`, `cross_encoder`) remain selectable
through `search.hybrid_search.reranker_type`.

## What an agent receives

- **MCP `search` tool** (`mcp/tools/search.py`). Session-free. It returns the
  ranked chunks as blocks headed `path:start-end  scope`, cut at a character
  budget on a line boundary (`search/context_pack.py`). `ai mcp --tools search`
  exposes only this tool.
- **`ai search`.** Prints `path:start-end [score]`, the enclosing symbol and a
  preview line.

## Measuring a change

Run the dev split for the suites a change affects, paired against the results
from before it:

```bash
uv run --group eval python -m evals run --suite scifact --arms inquiry --split dev --baseline <previous results.json>
```

`EVALS_INQUIRY_CONFIG=<file>` runs the `inquiry` arm on an alternative config
file for an ablation.
