---
title: "Data, analytics, and ML workloads"
type: "Reference"
status: "Active"
license: "Apache-2.0 OR MIT"
compatibility: "agentbundle-okf/v1"
research_claims:
  - WL-D1
  - WL-D1b
---
# Data, analytics, and ML workloads

<!--
Modified for AFP from Eugene Lim's agent-ready-repo.
Source: https://github.com/eugenelim/agent-ready-repo
Revision: c555e906df4c345d6c31b05f479976d2dd098ed4
AFP modifications: Copyright 2026 Sammy Basha, Apache-2.0.
-->

## Scope and routing signals

Use when pipelines, warehouses/lakes, transformations, features, training, models, experiments, or analytical serving are architecturally significant.

## Decisions and minimum evidence

Supports lineage, reproducibility, freshness, quality, isolation, and lifecycle decisions. Minimum evidence covers sources, ingestion, schemas, transformations, orchestration, data quality, lineage, storage layers, tenancy/access, versions, reproducibility, serving, monitoring, retention, and deletion.

## Architectural questions

- Which data/model version produced this result and can it be reproduced?
- How do late, corrected, revoked, or deleted inputs propagate?
- Where can training/analytical access exceed production-use authorization?

## Mechanisms and trade-offs

Batch/stream pipelines, immutable raw zones, versioned datasets/features/models, orchestration, quality gates, lineage, and monitoring trade freshness, cost, reproducibility, and operational load.

## Evidence and counter-evidence

Seek pipeline definitions, schemas, catalogues, quality checks, lineage, run metadata, model/data registries, access policies, serving traces, and deletion jobs. Counter-evidence includes notebooks and manual steps outside lineage.

## Failure modes and false positives

A model registry does not prove reproducibility; data freshness does not prove correctness; aggregate results can still leak sensitive information.

## Confirmation scenarios

Replay a run, backfill corrected data, revoke/delete one subject, introduce schema drift, fail a stage, promote/rollback a model, and trace outputs.

## Related concepts and escalation

Pair with data governance, event/batch workloads, cost, security/privacy, and knowledge retrieval where outputs feed context.

## Provenance and lifecycle

Synthesized from cloud data/ML architecture guidance and NIST AI risk guidance. Confidence: moderate; review annually.

Research claim trace: `WL-D1`, `WL-D1b`; see the [preserved source packet](../../provenance/workload-lenses/data-analytics-and-ml.json). Its dates and confidence belong to the original source; current web verification is not established.
