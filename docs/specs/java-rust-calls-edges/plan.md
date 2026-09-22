# Plan: Language-aware `calls` extraction

## Assumption trio

- **Files touched:** `agentic_inquiry/parsers/implementations/unified_code.py`
  (`_extract_call_info`, `_find_containing_definition_key`,
  `_find_containing_definition`, new module-level `_DEFINITION_NODE_TYPES`);
  new test file `tests/parsers/test_calls_extraction_multilang.py`.
- **Done when:** new Java + Rust regression tests assert the expected
  `calls` `target_name`s, and the existing Python `calls` tests still pass.
- **Not changing:** `queries/*.scm`, relationship resolution, and the
  behavior of grammars that never produced call edges.

## Declined patterns

- Tempted to build a per-language registry mapping every grammar to its
  call/def node types. **Declining** — structural field-probing (prefer the
  `function` field; fall back to `name`/`method` + `object`/`receiver`)
  handles Python, Java, Rust, Ruby, C#, PHP uniformly without a lookup
  table that would drift from the `.scm` files.
- Tempted to also fix Kotlin / PHP-simple / Swift call gaps while here.
  **Declining** — out of scope, unverified, pre-existing (their name nodes
  are `simple_identifier` / `name`, a separate concern).
- Tempted to delete the dead `id()`-based `_find_containing_definition`.
  **Declining deletion** — the issue references it; instead point it at the
  shared constant so it can't drift from the key-based twin.

## Design (the two fixes)

**Fix 1 — `_extract_call_info` probes structure, not Python grammar:**
1. Try `child_by_field_name("function")` (Python `call`; C-family / Rust /
   TS / C# `call_expression`/`invocation_expression`). If the func node is
   an `identifier` → simple call. If its type is in an accessor map
   (`attribute`→(object,attribute) [Py]; `member_expression`→(object,property)
   [JS/TS]; `field_expression`→(value,field) [Rust]) → method call.
2. Else fall back to `name`/`method` field (+ optional `object`/`receiver`)
   — Java `method_invocation`, Ruby `call`. Name present + receiver → method;
   name present, no receiver → function.
3. Else `None`. An `identifier` node (Java's `@call.method` capture, passed
   alongside the `@call` `method_invocation`) has no such fields → `None`,
   so no double-count.

**Fix 2 — `_DEFINITION_NODE_TYPES` covers Python/TS/JS/Java/Rust**, limited
to node types captured as processable `.def` elements (excludes
`arrow_function` and `mod_item`). Both container-finders use it.

## Tests (construction, red first)

`tests/parsers/test_calls_extraction_multilang.py`:
- `test_java_calls_extracted` — issue's two-file Java fixture →
  `calls` target_names ⊇ {applyTax, unitPrice, base}.
- `test_rust_calls_extracted` — Rust fixture with intra-file calls →
  target_names ⊇ {unit_price, base, helper}.
- `test_ruby_calls_not_regressed` — Ruby method-call fixture still yields a
  `calls` edge (guards the field-probing fallback).

## Verification mode

TDD for all three. Gates: `ruff check`, `mypy agentic_inquiry/`,
`pytest tests/parsers/`.
