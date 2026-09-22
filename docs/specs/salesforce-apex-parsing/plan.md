# Plan: Salesforce Apex parse depth

- **Spec:** [`spec.md`](spec.md)
- **Status:** Done

## Assumption trio

- **Files touched:** `agentic_inquiry/parsers/implementations/queries/apex.scm`;
  `agentic_inquiry/parsers/implementations/unified_code.py`
  (`_DEFINITION_NODE_TYPES`, `_extract_class_bases`);
  `tests/parsers/test_apex_extraction.py` (new);
  `tests/parsers/test_unified_code_all_languages.py`
  (`EXPECTED_MIN_ENTITIES["apex"]`); optional richer samples under
  `tests/parsers/samples/code/apex/`.
- **Done when:** the Apex TDD tests in `test_apex_extraction.py` pass and
  the all-language Apex floor is >= 2.
- **Not changing:** language-pack version, standalone SOQL/SOSL, recognizers,
  metadata XML, `EntityType` enum, new relationship types.

## Declined patterns

- Tempted to emit a `queries` relationship from `query_expression`.
  **Declining** - method-chunk text already makes SOQL searchable; named
  object edges belong with the later Apex recognizer.
- Tempted to add `EntityType.TRIGGER`. **Declining** - a trigger is a
  named top-level container; capture it as `@code_class` so it flows
  through the existing class chunk path.
- Tempted to upgrade `tree-sitter-language-pack` or add `.soql` files.
  **Declining** - explicitly out of this spec.

## Approach

Rewrite `apex.scm` to Java parity (classes without a `parser_output` parent,
methods, constructors, interfaces, enums, properties/fields, calls) plus
Apex-only `trigger_declaration` and superclass/interfaces captures. Put
`trigger_declaration` and `enum_declaration` in `_DEFINITION_NODE_TYPES` so
calls inside a trigger body attach to the trigger. Teach
`_extract_class_bases` to read `type_identifier` (and one nested
`type_list`) so Apex `extends` / `implements` become `inherits` edges.

## Construction tests

**Integration tests:** none beyond per-task tests.
**Manual verification:** none.

## Tasks

### T1: Apex TDD fixtures fail on current extraction

**Depends on:** none

**Mode:** TDD

**Tests:**
- `tests/parsers/test_apex_extraction.py` covering every Acceptance
  Criterion in `spec.md` (class/inner class/constructor/property/field/
  methods on `.cls`; trigger name on `.trigger`; `inherits`; `calls` with
  `source_name`; SOQL text in method content; enum symbol).
- Raise `EXPECTED_MIN_ENTITIES["apex"]` to 2 in
  `tests/parsers/test_unified_code_all_languages.py`.

**Approach:**
- Write the tests first; confirm they fail against today's `apex.scm`.

**Done when:** the new tests fail for missing symbols/edges, not for
import or fixture errors.

### T2: Query + definition-node + bases helper make T1 green

**Depends on:** T1

**Mode:** TDD

**Tests:** same file as T1, now passing; existing
`tests/parsers/test_calls_extraction_multilang.py` still green.

**Approach:**
- Replace `queries/apex.scm` with Java-parity patterns plus
  `trigger_declaration` as `@code_class` and `enum_declaration` as
  `@code_enum`. Use `@code_property.def` (Java's `@code_property` has no
  `.def` and is dropped by the chunker).
- Add `trigger_declaration` and `enum_declaration` to
  `_DEFINITION_NODE_TYPES`.
- In `_extract_class_bases`, accept `type_identifier` children and
  flatten one `type_list`; accumulate bases when a class has both
  `superclass` and `interfaces` captures (do not overwrite).

**Done when:** `uv run --env-file .env pytest tests/parsers/test_apex_extraction.py tests/parsers/test_calls_extraction_multilang.py tests/parsers/test_unified_code_all_languages.py -k apex -q` is green.

## Rollout

Big bang with the parser change. No flag, no migration, no infra.
Reversible by reverting the PR.

## Changelog

- 2026-09-04: initial plan (Phase 1 only; no language-pack bump).
- 2026-09-04: added TDD mode on T1/T2; interface and trigger-call tests.
