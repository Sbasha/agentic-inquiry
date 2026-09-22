# Spec: Salesforce intelligence (triggers, SOQL, routes, metadata allowlist)

Mode: full (new parser in the chain, config field, two cooperating
features in one PR)

- **Status:** Shipped
- **Owner:** sbasha
- **Plan:** [`plan.md`](plan.md)
- **Constrained by:** none
- **Brief:** none
- **Discovery:** none
- **Contract:** none
- **Shape:** mixed

## Objective

A Salesforce developer indexes a DX-shaped folder with `/ai:index`.
Asking what uses `Account` lists:

- the Apex trigger that runs on Account
- Apex methods whose SOQL `FROM` clause names Account
- `@AuraEnabled` / `@RestResource` / `@HttpGet` methods that expose Account work
- LWC modules that import `@salesforce/apex/Class.method`
- custom fields owned by Account (outbound ``salesforce_field``),
  Flows that DML Account or call Apex, and FlexiPages / layouts that
  bind Account

Those facts come from framework conventions and config XML, not from
the generic Apex grammar alone.

## Boundaries

### Always do

- Prefix new relationship types with `salesforce_`.
- Keep recognizers additive, idempotent, failure-safe, and cheap on
  the no-op path ([`recognizers/AGENTS.md`](../../../agentic_inquiry/parsers/recognizers/AGENTS.md)).
- Gate the metadata parser on filename suffix only; do not read file
  bytes in `can_parse`.
- Keep relationship `metadata` values LanceDB-simple (`str`, `int`,
  `float`, `bool`, `None`).

### Ask first

- A fifth metadata suffix beyond the allowlist below.
- A new `EntityType` enum member.

### Never do

- Add `tree-sitter-sfapex` or any new grammar package to
  `pyproject.toml`.
- Build extractors for the Salesforce metadata registry (PermissionSet,
  Profile, CustomMetadata, ValidationRule, Experience, Reports,
  `.cls-meta.xml`, and the rest).
- Route every `.xml` file through Salesforce extraction (Maven POMs,
  Spring XML, and `.cls-meta.xml` stay on the document parser).
- Upgrade `tree-sitter-language-pack` or add standalone `.soql` /
  `.sosl` languages.

## Testing Strategy

- **TDD** for recognizer edge extraction and metadata suffix dispatch
  (invariants: edge type + names; `can_parse` true/false).
- **TDD** for the chain-level fixture that proves recognizers run after
  `ParserChain.parse` on `.cls` / `.trigger`.
- **Goal-based** for config wiring: `ParsersConfig` exposes
  `salesforce_metadata` at priority 75; `available_parsers()` includes
  `salesforce_metadata`.

## Acceptance Criteria

- [x] Parsing a `.trigger` file that declares `on Account` produces a
      `salesforce_observes` relationship whose `target_name` is
      `Account` and whose `metadata.events` lists the trigger events.
- [x] Parsing a `.cls` method whose body contains
      `[SELECT Id FROM Account]` produces `salesforce_queries` from
      that method to `Account`.
- [x] Parsing a class with `@RestResource(urlMapping='/accounts/*')`
      and `@HttpGet` on a method produces `salesforce_route` with
      `http_method=GET` and `path=/accounts/*`.
- [x] Parsing a method annotated `@AuraEnabled` produces
      `salesforce_route` with `aura_enabled=true`.
- [x] Parsing a `.js` file that imports
      `@salesforce/apex/AccountApi.find` produces `salesforce_invokes`
      to `AccountApi.find`.
- [x] A `.java` file and a `.js` file without `@salesforce/apex`
      produce zero `salesforce_*` relationships.
- [x] Running the Apex recognizer twice on the same document does not
      duplicate relationships.
- [x] `can_parse` is true for `.object-meta.xml`, `.field-meta.xml`,
      `.flow-meta.xml`, `.flexipage-meta.xml`, and `.layout-meta.xml`,
      and false for `pom.xml` and `Account.cls-meta.xml`.
- [x] A field file under `objects/Account/fields/Status__c.field-meta.xml`
      produces `salesforce_field` from `Account` to `Status__c`.
- [x] A Flow whose XML contains `<object>Account</object>` and an Apex
      `<actionName>AccountService</actionName>` produces
      `salesforce_touches` to `Account` and `salesforce_invokes` to
      `AccountService`.
- [x] A layout named `Account-Account Layout.layout-meta.xml` produces
      `salesforce_touches` to `Account`.
- [x] A FlexiPage with `<sobjectType>Account</sobjectType>` produces
      `salesforce_touches` to `Account`.
- [x] Existing parser tests and Spring/FastAPI recognizer tests still
      pass.

## Assumptions

- Technical: Phase 1 Apex extraction is shipped (`docs/specs/salesforce-apex-parsing/spec.md`, commit `feat(parsers): extract Apex classes...`).
- Technical: recognizers dispatch on `Path.suffix` and attach to existing chunks (`agentic_inquiry/parsers/recognizers/base.py`).
- Technical: Apex annotations are `annotation` / `identifier` nodes; triggers expose `name`, `object`, `events`; SOQL FROM is `from_clause` / `storage_identifier` (probe `get_parser("apex")` 2026-09-04).
- Technical: `.xml` is not claimed by `UnifiedCodeParser` (no `xml.scm`); `DocumentParser` claims `.xml` at priority 50 (`languages.py`, `document.py`, `config.py`).
- Technical: `ParsersConfig(...)` call sites pass named fields and tolerate a new defaulted field (`tests/conftest.py`).
- Process: full mode because this adds a parser module, a config field, and two features (work-loop risk triggers).
- Product: 3a and 3b ship in one PR; no registry-wide metadata catalog (source: user confirmation 2026-09-04).
