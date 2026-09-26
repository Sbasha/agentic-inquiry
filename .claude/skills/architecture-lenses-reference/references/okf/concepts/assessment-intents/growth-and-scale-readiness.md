---
title: "Growth and scale readiness"
type: "Reference"
status: "Active"
license: "Apache-2.0 OR MIT"
compatibility: "agentbundle-okf/v1"
research_claims:
  - AI-G1
  - AI-G1b
---
# Growth and scale readiness

<!--
Modified for AFP from Eugene Lim's agent-ready-repo.
Source: https://github.com/eugenelim/agent-ready-repo
Revision: c555e906df4c345d6c31b05f479976d2dd098ed4
AFP modifications: Copyright 2026 Sammy Basha, Apache-2.0.
-->

## Scope and routing signals

Use when a named future demand, capability, market, data volume, tenancy, or organizational scale could exceed current architecture runway.

## Decisions and minimum evidence

Supports staged readiness investment and trigger thresholds. Minimum evidence names future scenario and horizon, current baseline, demand/capacity model, sensitivity points, provider limits, team constraints, and reversible experiments.

## Architectural questions

- What specifically grows, by how much, when, and with what workload shape?
- Which resource, boundary, state model, or team interaction becomes sensitive first?
- What leading signal justifies the next investment?

## Mechanisms and trade-offs

Partitioning, elasticity, asynchronous work, quotas, modularization, platform investment, and staffing trade current simplicity/cost against future runway.

## Evidence and counter-evidence

Seek demand forecasts with ranges, workload records, capacity tests, provider contracts, change coupling, and team topology. Counter-evidence includes speculative hockey-stick demand and irrelevant headline limits.

## Failure modes and false positives

Current success does not prove future readiness; present coupling does not require decomposition absent a credible scenario; provider marketing is not a binding limit.

## Confirmation scenarios

Stress the top future scenario through capacity, failure, recovery, deployment, and ownership; record the first threshold and cheapest experiment.

## Related concepts and escalation

Pair with trade-offs/sensitivity, performance, reliability, system shape, and provider grounding. Material target-architecture choices may hand off to design.

## Provenance and lifecycle

Synthesized from mission-critical capacity guidance, cloud design-for-change guidance, and ATAM scenarios. Confidence: high; review annually.

Research claim trace: `AI-G1`, `AI-G1b`; see the [preserved source packet](../../provenance/assessment-intents/growth-and-scale-readiness.json). Its dates and confidence belong to the original source; current web verification is not established.
