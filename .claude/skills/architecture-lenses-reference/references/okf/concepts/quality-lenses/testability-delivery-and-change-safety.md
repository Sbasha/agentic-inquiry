---
title: "Testability, delivery, and change safety"
type: "Reference"
status: "Active"
license: "Apache-2.0 OR MIT"
compatibility: "agentbundle-okf/v1"
research_claims:
  - QL-T1
  - QL-T1b
---
# Testability, delivery, and change safety

<!--
Modified for AFP from Eugene Lim's agent-ready-repo.
Source: https://github.com/eugenelim/agent-ready-repo
Revision: c555e906df4c345d6c31b05f479976d2dd098ed4
AFP modifications: Copyright 2026 Sammy Basha, Apache-2.0.
-->

## Scope and routing signals

Use when confidence in change, rollback, interface behavior, migration, or failure handling is architecturally significant.

## Decisions and minimum evidence

Supports whether changes can be validated and released safely. Minimum evidence maps architecture contracts to test levels, environments, data, fault cases, deployment gates, observability, rollback, and ownership without relying on mock-shape assertions.

## Architectural questions

- Which consequential contract is proved at the cheapest faithful level?
- Where do mocks or fixtures diverge from real provider, policy, database, or runtime behavior?
- Can the system detect, contain, and reverse a bad change?

## Mechanisms and trade-offs

Contract tests, characterization tests, component integration, production-like environments, fault injection, canaries, feature controls, and rollback trade speed, fidelity, cost, and flakiness.

## Evidence and counter-evidence

Seek test topology, failure cases, schema/provider integration, release gates, flaky-test data, deployment outcomes, and rollback exercises. Counter-evidence includes skipped suites and tautological tests.

## Failure modes and false positives

Annotation lint is not type safety; coverage percentage is not contract coverage; unit tests alone do not prove cross-boundary behavior.

## Confirmation scenarios

Change one critical contract and verify the right tests fail; exercise deployment failure, rollback, and post-release signals.

## Related concepts and escalation

Pair with delivery patterns, maintainability, transformation, reliability, and every workload contract. Escalate test-quality review to quality engineering.

## Provenance and lifecycle

Synthesized from DORA delivery research, SEI scenario evaluation, and well-architected operational guidance. Confidence: high; review annually.

Research claim trace: `QL-T1`, `QL-T1b`; see the [preserved source packet](../../provenance/quality-lenses/testability-delivery-and-change-safety.json). Its dates and confidence belong to the original source; current web verification is not established.
