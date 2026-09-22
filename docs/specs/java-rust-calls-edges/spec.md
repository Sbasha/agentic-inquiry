# Spec: Language-aware `calls` graph-edge extraction (Java, Rust, …)

Mode: light (no risk trigger fired)

- **Status:** Shipped (2026-07-07)

Issue: [#179](https://github.com/sbasha/311256_agentic-inquiry/issues/179)

## Objective

Method-to-method `calls` graph edges are never produced for **Java** or
**Rust** (and are silently absent for several other grammars), even though
entity extraction and the tree-sitter `queries/*.scm` files are correct. The
failure is two Python-grammar hardcodings in
`agentic_inquiry/parsers/implementations/unified_code.py`:

1. `_extract_call_info()` assumes Python's `call` node shape — it reads the
   `function` field and branches on `identifier` / `attribute` node types.
   Java's `method_invocation` uses `name` + `object` fields; Rust's method
   calls nest a `field_expression`; neither is recognized, so `call_info` is
   `None`.
2. `_find_containing_definition_key()` (and the unused `id()`-based
   `_find_containing_definition()`) only recognize Python container node
   types (`function_definition`, `class_definition`, `method_definition`), so
   an extracted call can't be attributed to its containing Java/Rust
   definition even if it were extracted.

Make both **language-aware by structural probing** (field presence + node
type), not hardcoded to one grammar.

## Acceptance Criteria

- [x] Indexing a small Java fixture (two files with known intra- and
  cross-file calls) produces `calls` relationships whose `target_name`s
  include `applyTax`, `unitPrice`, and `base` (the issue's fixture).
- [x] Indexing a small Rust fixture with known intra-file calls produces
  `calls` relationships whose `target_name`s include the called
  functions/methods (e.g. `unit_price`, `base`, `helper`).
- [x] The existing Python `calls` extraction tests
  (`tests/parsers/test_relationship_extraction.py`) still pass unchanged —
  no regression to the passing baseline.
- [x] No regression for other grammars that currently produce `calls`
  edges — in particular **C#** (`invocation_expression` simple calls),
  which the old Python-shaped code happened to handle and a naive
  node-type dispatch would have broken. **Ruby** (`call` node with
  `method`/`receiver` fields, no `function` field) produced *zero* edges
  before — the old code extracted a `call_info` but attribution failed
  because Ruby's container node types weren't recognized. The general
  field-probing fallback plus Ruby's def node types in the shared
  container set make Ruby an incidental beneficiary; the Ruby test guards
  that fallback. **PHP** (`member_call_expression`) and **C++** method
  calls likewise gain correct edges from the same general mechanism — not
  targeted work, a consequence of probing structure instead of hardcoding
  Python's grammar. (C++'s `field_expression` names the receiver `argument`,
  not Rust's `value`; the accessor map lists both candidates so the `object`
  metadata is preserved, not just the target.)
- [x] **Go** method calls (`selector_expression` target, `operand`/`field`)
  are extracted. Go simple calls always worked (`identifier` target); method
  calls hit the same failure class as Java/Rust and are fixed by one accessor
  entry. Added on PR review (#182) since Go's query file and container types
  were already in place — same mechanism, one line.
- [x] Extraction is not double-counted for grammars (Java) where the query
  captures both the whole call node (`@call`) and its name identifier
  (`@call.method`) for the same invocation. More generally, a single call
  site yields exactly one `calls` edge even when a query file captures it
  under multiple patterns (`cpp.scm` ships two byte-identical
  `@call.method` patterns) — calls are de-duped by node byte span,
  mirroring the existing definition de-dup.

## Boundaries

- **In scope:** `_extract_call_info`, `_find_containing_definition_key`,
  `_find_containing_definition`, and a module-level set of definition node
  types, all in `unified_code.py`. New regression tests for Java, Rust, Go,
  Ruby, and C++.
- **Out of scope:** the `queries/*.scm` files (already correct); the
  relationship *resolution* layer (already works — Python proves it);
  `ai entity --verbose` display thinness (noted separately in the issue);
  adding brand-new call support for grammars that never worked (Kotlin,
  PHP simple calls, Swift use non-`identifier` name nodes — pre-existing
  gaps, left alone).

## Testing Strategy

TDD. Parser-level regression tests mirroring the existing Python tests in
`tests/parsers/test_relationship_extraction.py`: build a fixture with
`tmp_path`, `await parser.parse(...)`, collect `chunk.relationships`, filter
`type == "calls"`, assert on `target_name`. This is the correct unit — the
fix is in the parser, and the issue confirms the downstream
relationship-building/resolution machinery already works.

## Assumptions

- `tree_sitter_language_pack` can parse Java and Rust in this environment
  (verified during PLAN via a probe of node types/fields).
- The container node found by walking up from a call must have the same
  `(start_byte, end_byte)` as a captured `@code_*.def` element, so only
  node types captured as processable `.def` elements are added to the
  container set (notably **not** `arrow_function` (`@code_function.arrow`)
  nor Rust `mod_item` (`@code_module`), which are not processed as elements
  and would silently swallow calls).
