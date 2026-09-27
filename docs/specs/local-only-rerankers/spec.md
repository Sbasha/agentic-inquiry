# Spec: Local-only rerankers

Mode: light (borderline: removes a value from the published config schema,
but the scope call is settled by the charter and the change is a mechanical
removal with no new code. Escalate if anything structural surfaces.)

- **Status:** Shipped (2026-09-26)
- **Constrained by:** [`CHARTER.md`](../../CHARTER.md) Principle 1 (Local only, by design)

## Objective

Every hybrid-search reranker runs on the user's machine. `reranker_type`
accepts `rrf`, `linear_combination`, `cross_encoder` and `colbert`; a
reranker that sends queries and indexed content to a hosted API is not a
configuration option, because the charter rules out any feature that needs a
hosted service to work. A config that names a hosted reranker such as
`cohere` fails at load with a `ConfigurationError` that lists the valid
options.

## Acceptance Criteria

- [x] `config/config.schema.json` `reranker_type` enum is exactly `rrf`,
      `linear_combination`, `cross_encoder`, `colbert`, and neither the
      `reranker_type` nor the `reranker_params` description mentions an
      API-based reranker or API key.
- [x] `VALID_RERANKER_TYPES` in `agentic_inquiry/search/hybrid_search.py`
      equals the schema enum
      (`tests/search/test_reranker_validation.py::TestRerankerConfigValidation::test_valid_reranker_types_match_config_schema`).
- [x] No reranker is registered under `cohere`:
      `agentic_inquiry/search/rerankers/cohere.py` does not exist and
      `agentic_inquiry.search.rerankers` does not export `CohereReranker`.
- [x] `Config._validate_config` raises `ConfigurationError` for
      `reranker_type: cohere`
      (`tests/integration/test_reranker_configuration.py::TestRerankerConfiguration::test_invalid_reranker_type[cohere]`).
- [x] `SearchService` raises `ConfigurationError` naming `cohere` and the
      valid options when `reranker_type` is `cohere`
      (`tests/search/test_reranker_validation.py`).
- [x] `docs/architecture/search.md` and code docstrings list only the four
      local reranker types.

## Boundaries

- **Always do:** keep the schema enum and `VALID_RERANKER_TYPES` identical.
- **Ask first:** changing the other rerankers' behavior or the embedding
  providers; editing `CHANGELOG.md`.
- **Never do:** add a reranker that calls a hosted API, or a dependency to
  support one.

## Testing Strategy

Tests at both validation layers (schema at config load, `SearchService`
startup), pinned to the reranker set and to each other, plus
`git grep -iw cohere -- agentic_inquiry config docs/architecture` returning
nothing.
