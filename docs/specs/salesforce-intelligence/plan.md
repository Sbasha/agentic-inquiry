# Plan: Salesforce intelligence

- **Spec:** [`spec.md`](spec.md)
- **Status:** Done

## Assumption trio

- **Files touched:** recognizers `apex_salesforce.py`, `lwc_salesforce.py`,
  `recognizers/__init__.py`; parser
  `implementations/salesforce_metadata.py` + `__init__.py`;
  `config.py` `ParsersConfig`; `chain.py`; tests under
  `tests/parsers/recognizers/` and `tests/parsers/`.
- **Done when:** the Acceptance Criteria tests are green and Spring /
  FastAPI / Apex parse-depth tests still pass.
- **Not changing:** language-pack version, `EntityType`, the Apex `.scm`
  query file, metadata types outside the five suffixes.

## Declined patterns

- Tempted to subclass `HTTPRouteRecognizer` for the Apex file.
  **Declining** - triggers and SOQL are not HTTP.
- Tempted to run a recognizer on every `.xml`. **Declining** - suffix
  parser at priority 75 keeps POMs on DocumentParser.
- Tempted to add `EntityType` members for object/flow. **Declining** -
  chunks + `salesforce_*` edges are the consumer.

## Approach

1. Apex + LWC recognizers, Spring-shaped unit tests, register builtins.
2. Suffix-gated metadata parser, config priority 75, chain wiring.
3. Chain-level fixture that runs `ParserChain.parse` on Apex.

## Tasks

### T1: Apex and LWC recognizers emit `salesforce_*` edges

**Depends on:** none

**Mode:** TDD

**Touches:** `agent_vault/parsers/recognizers/apex_salesforce.py`,
`agent_vault/parsers/recognizers/lwc_salesforce.py`,
`agent_vault/parsers/recognizers/__init__.py`,
`tests/parsers/recognizers/test_apex_salesforce.py`,
`tests/parsers/recognizers/test_lwc_salesforce.py`

**Tests:**
- Trigger observes Account with events metadata.
- Method queries Account from SOQL FROM.
- `@HttpGet` + `@RestResource` urlMapping → `salesforce_route`.
- `@AuraEnabled` → `salesforce_route` with `aura_enabled=true`.
- LWC `@salesforce/apex/AccountApi.find` → `salesforce_invokes`.
- Java file and plain JS: zero `salesforce_*` edges.
- Enrich twice: same relationship set.

**Approach:**
- Standalone recognizers (Spring DI family). Pre-filter bytes, re-parse
  Apex via `get_parser("apex")`. Attach by `element_name`.
- LWC: regex after a `@salesforce/apex/` byte scan.

**Done when:** the two new test modules pass.

### T2: Metadata parser claims the five suffixes

**Depends on:** none

**Mode:** TDD

**Touches:** `agent_vault/parsers/implementations/salesforce_metadata.py`,
`agent_vault/parsers/implementations/__init__.py`,
`agent_vault/config.py`, `agent_vault/parsers/chain.py`,
`tests/parsers/test_salesforce_metadata.py`

**Tests:**
- `can_parse` true/false per AC.
- Field / Flow / layout / FlexiPage edges per AC.
- `available_parsers()` contains `salesforce_metadata`.

**Approach:**
- Stdlib ElementTree, strip XML namespaces by local tag name.
- Object name from path for fields; filename prefix for layouts.

**Done when:** `test_salesforce_metadata.py` is green.

### T3: Chain-level Apex fixture

**Depends on:** T1

**Mode:** TDD

**Touches:** `tests/parsers/test_salesforce_chain.py`

**Tests:**
- `ParserChain.parse` on a `.trigger` and a `.cls` with SOQL yields
  `salesforce_observes` and `salesforce_queries`.

**Done when:** that test is green.

## Rollout

Big bang with the parser change. Reversible by revert. No migration.

## Changelog

- 2026-09-04: initial plan (3a + 3b in one PR).
