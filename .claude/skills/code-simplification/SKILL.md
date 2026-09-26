---
name: code-simplification
description: Review and refactor code to make it simpler, more maintainable, and easier to understand without changing required behavior. Use when the user asks to reduce complexity, remove unnecessary abstractions, clarify control flow, consolidate duplication, or simplify a recently implemented solution while preserving its tests and public contracts.
---

# Simplify code without changing behavior

Reduce the amount a maintainer must understand while preserving the required behavior, public contracts, error handling, data protection, authorization boundaries and performance characteristics.
Do not use this skill to invent a feature, remove a requirement, or replace working code because another style is possible.

## Establish the boundary

Read the repository instructions, relevant design decisions, tests, and changed code.
State the behavior and interfaces that must remain stable.
If the user has not authorized edits, review only.
If the requested simplification would remove behavior or change a public contract, explain the trade-off and ask before proceeding.

## Find earned simplifications

Look for concrete maintenance costs:

- nested control flow that guard clauses can flatten;
- functions with unrelated responsibilities;
- abstractions that have one caller and hide no meaningful complexity;
- repeated logic that already changes together;
- indirect names or intermediate values that obscure the operation;
- generic data structures that make a fixed domain harder to see; and
- unused parameters, branches, methods, or types.

Keep complexity when it carries a real constraint such as compatibility, performance, security, type safety, or a second confirmed use case.
Do not replace one large module with many shallow pass-through files.

## Make the change

Prefer the smallest coherent refactor that removes the identified cost.
Preserve repository conventions and keep each edit traceable to a specific simplification.
Add or update tests only when the existing suite does not protect the behavior being preserved.

## Verify

Run the closest behavior tests first, followed by the repository's required checks in proportion to the change.
Inspect the final diff for accidental contract, error, dependency, or formatting changes.
If a relevant check cannot run, report that limit instead of treating the refactor as proven.

## Report

State:

- what became simpler;
- which behavior and contracts stayed unchanged;
- the validation run; and
- any remaining necessary complexity or unverified risk.
