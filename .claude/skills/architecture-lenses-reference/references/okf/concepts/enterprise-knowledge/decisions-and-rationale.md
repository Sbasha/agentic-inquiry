---
title: "Enterprise decisions and rationale"
type: "Reference"
status: "Active"
license: "Apache-2.0 OR MIT"
compatibility: "agentbundle-okf/v1"
research_claims:
  - DR-1
  - DR-1b
---
# Enterprise decisions and rationale

<!--
Modified for AFP from Eugene Lim's agent-ready-repo.
Source: https://github.com/eugenelim/agent-ready-repo
Revision: c555e906df4c345d6c31b05f479976d2dd098ed4
AFP modifications: Copyright 2026 Sammy Basha, Apache-2.0.
-->

## Scope and routing signals

Use when past options, commitments, waivers, incidents, acquisitions, or
organizational changes explain current architecture or constrain future action.

## Decisions and minimum evidence

Supports whether to preserve, revisit, or supersede a decision. Minimum evidence
identifies decision, owner, date, context, options, drivers, consequences,
supersession state, and current applicability.

## Architectural questions

- Which forces made the decision reasonable at the time?
- Which assumptions or constraints have changed?
- What compatibility, data, contractual, or organizational cost makes reversal hard?

## Mechanisms and trade-offs

Decision records and time-ordered evidence preserve rationale. Formal records
improve continuity but cannot replace checking implemented state and lived consequences.

## Evidence and counter-evidence

Seek ADRs, review records, incident follow-ups, exception decisions, roadmaps,
and owner confirmation. Counter-evidence includes later supersession, abandoned
implementation, changed requirements, and undocumented local exceptions.

## Failure modes and false positives

Old is not wrong and undocumented is not necessarily accidental. A decision
record can be authoritative history while no longer governing current behavior.

## Confirmation scenarios

Reconstruct one consequential choice from pre-decision context through
implementation, operational outcome, and current owner judgment.

## Related concepts and escalation

Pair with foundations decisions/constraints, in-flight work, and transformation.
Use decision archaeology when rationale reconstruction becomes the primary task.

## Provenance and lifecycle

Synthesized from ISO architecture rationale, SEI evaluation/modernization
methods, and cloud continuous-improvement guidance. Confidence: high; review annually.

Research claim trace: `DR-1`, `DR-1b`; see the [preserved source packet](../../provenance/enterprise-knowledge/decisions-and-rationale.json). Its dates and confidence belong to the original source; current web verification is not established.
