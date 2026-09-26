---
title: "Data integrity, lifecycle, and governance"
type: "Reference"
status: "Active"
license: "Apache-2.0 OR MIT"
compatibility: "agentbundle-okf/v1"
research_claims:
  - QL-D1
  - QL-D1b
---
# Data integrity, lifecycle, and governance

<!--
Modified for AFP from Eugene Lim's agent-ready-repo.
Source: https://github.com/eugenelim/agent-ready-repo
Revision: c555e906df4c345d6c31b05f479976d2dd098ed4
AFP modifications: Copyright 2026 Sammy Basha, Apache-2.0.
-->

## Scope and routing signals

Use when data ownership, correctness, lineage, schema evolution, retention, deletion, privacy, or derived copies drive architecture risk.

## Decisions and minimum evidence

Supports data-boundary and lifecycle decisions. Minimum evidence identifies authoritative source, schema/semantics, owner, consistency model, validation, lineage, derived stores/caches, access scope, retention/deletion, migration, backup/restore, and reconciliation.

## Architectural questions

- Which system owns truth and which copies can be rebuilt?
- How do schema, ACL, correction, deletion, and provenance propagate?
- What happens during partial failure, replay, migration, or concurrent update?

## Mechanisms and trade-offs

Transactions, constraints, idempotency, versioned schemas, lineage, change data capture, reconciliation, retention policies, and immutable history trade latency, availability, cost, and operational complexity.

## Evidence and counter-evidence

Seek schemas, migrations, constraints, data flows, retention jobs, lineage, reconciliation, access tests, and recovery evidence. Counter-evidence includes shadow stores and manual repair.

## Failure modes and false positives

A database transaction does not protect external side effects; eventual consistency is not automatically incorrect; deletion in one store may not reach indexes or caches.

## Confirmation scenarios

Create, update, revoke, delete, restore, replay, and migrate one representative record across every authoritative and derived store.

## Related concepts and escalation

Pair with event-driven, analytics, knowledge retrieval, security/privacy, and modernization. Escalate legal retention interpretation to accountable owners.

## Provenance and lifecycle

Synthesized from cloud data/reliability guidance and secure multitenant retrieval architectures. Confidence: high; review annually.

Research claim trace: `QL-D1`, `QL-D1b`; see the [preserved source packet](../../provenance/quality-lenses/data-integrity-lifecycle-and-governance.json). Its dates and confidence belong to the original source; current web verification is not established.
