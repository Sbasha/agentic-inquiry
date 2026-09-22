# Spec: Salesforce Apex parse depth

Mode: light (no risk trigger fired)

- **Status:** Shipped
- **Owner:** sbasha
- **Plan:** [`plan.md`](plan.md)
- **Constrained by:** none
- **Brief:** none
- **Discovery:** none
- **Contract:** none
- **Shape:** service

## Objective

A Salesforce developer indexes a DX folder with `/ai:index`. Apex classes
(`.cls` / `.apex`) and triggers (`.trigger`) produce the same kind of
searchable symbols and graph edges Java already does: classes (including
inner classes), interfaces, enums, methods, constructors, fields and
properties, method calls, and superclass / interface inheritance. A method
that runs a SOQL query in brackets (`[SELECT ... FROM Account]`) keeps that
query text in its chunk, so `/ai:search` can find the object without a
separate query language. Named `queries` edges, `@AuraEnabled` routing, and
metadata XML (`*.object-meta.xml`, Flows, layouts) are out of this spec.

## Boundaries

### Always do

- Match Apex query captures to the existing `@code_class` / `@code_method` /
  `@code_interface` / `@code_enum` / `@code_property` / `@call` /
  `@code_class.bases` convention so the unified chunker does not drop them.
- Keep parser `metadata` values LanceDB-simple (`str`, `int`, `float`,
  `bool`, `None`).
- Treat `.cls`, `.trigger`, and `.apex` as the Apex language via
  `LanguageRegistry` (already mapped).

### Ask first

- Adding a new `EntityType` (for example `trigger`) or a new relationship
  type (`queries`, `observes`).
- Capturing standalone `.soql` / `.sosl` files or bumping
  `tree-sitter-language-pack`.

### Never do

- Add `tree-sitter-sfapex` (or any new grammar package) to `pyproject.toml`.
- Introduce a Salesforce recognizer, LWC/Aura wiring, or a metadata-XML
  parser in this spec.
- Build per-type extractors for the Salesforce metadata registry.

## Testing Strategy

TDD. Parser-level tests on `tmp_path` fixtures, same shape as
`tests/parsers/test_calls_extraction_multilang.py`: `await parser.parse(...)`,
assert on chunk `element_name` / `symbols` / `relationships`. The all-language
smoke test raises Apex's entity floor so a silent extraction regression fails
CI. No manual QA: there is no UI.

## Acceptance Criteria

- [x] Parsing a `.cls` file with a top-level class, an inner class, a
      constructor, a property (`get; set;`), a field, and two methods
      produces chunks whose symbols include those names.
- [x] Parsing a `.trigger` file produces a named chunk for the trigger
      (the trigger name is in `symbols` or `element_name`).
- [x] Parsing an Apex class that `extends BaseService` and
      `implements Schedulable` produces `inherits` relationships whose
      `target_name`s include `BaseService` and `Schedulable`.
- [x] Parsing an Apex method that calls `find()` and `Math.abs(...)`
      produces `calls` relationships whose `target_name`s include `find`
      and `abs`, attributed to that method (`source_name`).
- [x] Parsing a method whose body contains
      `[SELECT Id FROM Account WHERE Name = :name]` keeps that SOQL text
      in the method chunk's `content`.
- [x] An enum declaration produces a chunk/symbol for the enum name.
- [x] An interface declaration produces a chunk/symbol for the interface
      name.
- [x] A call inside a trigger body is attributed to the trigger
      (`source_name` is the trigger name).
- [x] `EXPECTED_MIN_ENTITIES["apex"]` is at least 2.
- [x] Existing parser tests still pass; Java/Python `calls` extraction is
      unchanged.

## Assumptions

- Technical: Apex is already registered (`.apex` / `.cls` / `.trigger`) and parsed via `tree_sitter_language_pack.get_parser("apex")` (source: `agentic_inquiry/parsers/implementations/utils/languages.py`, `pyproject.toml`).
- Technical: pack 0.10.0's Apex grammar exposes `class_declaration`, `trigger_declaration` (fields `name`, `object`, `events`, `body`), `constructor_declaration`, `enum_declaration`, `field_declaration` + `accessor_list`, `method_invocation` (`name` field, Java-shaped), `query_expression` / `soql_query_body`, `superclass` / `interfaces` with `type_identifier` children (source: probe `uv run python` against `get_parser("apex")` on 2026-09-04).
- Technical: `_extract_call_info` already handles Java `method_invocation` via the `name`/`object` shape; Apex needs the query capture plus `trigger_declaration` in `_DEFINITION_NODE_TYPES` so trigger-body calls attach (source: `unified_code.py`, java-rust-calls-edges spec).
- Technical: `_extract_class_bases` only reads `identifier` / `attribute` / `subscript` / `call` children, so Apex `type_identifier` names are dropped unless that helper also accepts `type_identifier` (source: `unified_code.py` `_extract_class_bases`).
- Process: light mode; same lean spec shape as `docs/specs/java-rust-calls-edges/spec.md` (source: work-loop risk triggers; no new dependency, module, or public API).
- Product: this spec is Apex parse depth only; Phase 3 recognizer and metadata-XML allowlist stay later (source: user confirmation 2026-09-04).
- Product: named SOQL-object graph edges are not required here; method-chunk text is enough for search (source: user confirmation 2026-09-04).
