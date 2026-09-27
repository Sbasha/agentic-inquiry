# Spec: Hybrid-search reranker defaults to RRF on every load path

Mode: light (no risk trigger fired: one field default in `config.py` plus
tests. The published contract, `config/config.schema.json`, already declares
`rrf` as the default; this makes the runtime honor it.)

- **Status:** Shipped (2026-09-26)
- **Plan:** task list below (light mode)
- **Constrained by:** none

## Objective

Hybrid search fuses vector and full-text results with Reciprocal Rank Fusion
unless the user picks another reranker. That holds whichever way the
configuration is loaded: from the packaged `default.yaml` when the user has no
config, or from a project (`agentic-inquiry.yaml`), global
(`~/.agentic-inquiry/config.yaml`) or `INQUIRY_CONFIG` file that omits
`search.hybrid_search.reranker_type`. A user file replaces the packaged file
rather than overlaying it, so an omitted key resolves to the
`HybridSearchConfig` dataclass default; that default is `"rrf"`, matching the
schema, the packaged YAML and `docs/architecture/search.md`. A user whose
config file has no `reranker_type` (including one started from
`agentic-inquiry.yaml.example`, where the `hybrid_search` block is commented
out) ranks with RRF; setting `reranker_type: linear_combination` selects the
weighted-score reranker instead. The rationale
for RRF is recorded in
[`design-decisions.md` § Reciprocal Rank Fusion for Hybrid Search](../../architecture/design-decisions.md#decision-reciprocal-rank-fusion-for-hybrid-search).

## Acceptance Criteria

- [x] `Config.load()` with no user config anywhere (clean cwd and `HOME`, no
      `INQUIRY_*` overrides) yields `search.hybrid_search.reranker_type == "rrf"`.
- [x] A config file whose `search.hybrid_search` section omits
      `reranker_type` yields `"rrf"`.
- [x] `HybridSearchConfig().reranker_type`, the schema's
      `search.hybrid_search.reranker_type.default` and the packaged
      `default.yaml` value are all `"rrf"`, and a unit test fails if any one
      drifts.

## Tasks

1. Tests (red): tighten `TestRerankerTypeValidation.test_default_reranker_type`
   in `tests/unit/test_config_storage.py` to assert `"rrf"`; add an isolated
   `Config.load()` test and a test that the dataclass, schema and packaged
   YAML declare the same default.
2. Code (green): set `HybridSearchConfig.reranker_type` to `"rrf"` in
   `agentic_inquiry/config.py`.
