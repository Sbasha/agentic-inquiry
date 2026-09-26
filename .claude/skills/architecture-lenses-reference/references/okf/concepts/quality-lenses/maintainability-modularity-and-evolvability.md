---
title: "Maintainability, modularity, and evolvability"
type: "Reference"
status: "Active"
license: "Apache-2.0 OR MIT"
compatibility: "agentbundle-okf/v1"
research_claims:
  - QL-M1
  - QL-M1b
---
# Maintainability, modularity, and evolvability

<!--
Modified for AFP from Eugene Lim's agent-ready-repo.
Source: https://github.com/eugenelim/agent-ready-repo
Revision: c555e906df4c345d6c31b05f479976d2dd098ed4
AFP modifications: Copyright 2026 Sammy Basha, Apache-2.0.
-->

## Scope and routing signals

Use when change coupling, responsibility clarity, dependency direction, knowledge concentration, or structural evolution dominates risk.

## Decisions and minimum evidence

Supports boundary and modernization sequencing decisions. Minimum evidence names change scenario, responsibilities, dependencies, contracts, build/deploy coupling, ownership, characterization coverage, churn/incidents, and cost of representative changes.

## Architectural questions

- Can one responsibility change without unrelated code, teams, data, or deployments?
- Which dependencies are stable contracts versus incidental reach-through?
- Where do boundaries reduce or merely relocate complexity?

## Mechanisms and trade-offs

Modules, ports/adapters, encapsulation, stable interfaces, dependency rules, ownership, and incremental extraction trade indirection, duplication, performance, and migration effort.

## Evidence and counter-evidence

Seek import/dependency graphs, change history, tests, interface types, build units, ownership, and incident patterns. Counter-evidence includes coherent large modules and artificial service layers.

## Failure modes and false positives

File size or fan-in alone is not poor architecture; more services do not imply modularity; forwarding layers can add ceremony without changing coupling.

## Confirmation scenarios

Implement or simulate one representative change and observe files, contracts, teams, data, tests, and deployment units affected.

## Related concepts and escalation

Pair with transformation, layered/modular shape, monorepo/platform shape, and delivery safety. Hand target redesign to architect-design.

## Provenance and lifecycle

Synthesized from ISO quality models, DORA loose-coupling research, and cloud design-for-change guidance. Confidence: high; review annually.

Research claim trace: `QL-M1`, `QL-M1b`; see the [preserved source packet](../../provenance/quality-lenses/maintainability-modularity-and-evolvability.json). Its dates and confidence belong to the original source; current web verification is not established.
