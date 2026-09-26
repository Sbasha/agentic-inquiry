---
name: agent-runtime
description: "Implement or review agent execution loops, tool dispatch, durable state, cancellation and recovery. Use for agent authority and uncertain tool outcomes; skill-file authoring and general project orchestration stay with their existing owners."
metadata:
  source-state: authored
  native-qualification: not-run
---

# Agent runtime and tool effects

Trace one actual request through the project's agent entry point, context construction, model call, tool dispatcher, durable state and final result. Read the pinned provider SDK and existing runtime code before choosing APIs. Identify which component owns the task, which identity authorizes each effect and which evidence determines completion.

## Implement the assigned runtime behavior

- Keep authoritative intent and tool permissions outside model-authored arguments. Validate the selected tool, arguments, tenant/resource scope and allowed effect at dispatch. Retrieved text, tool descriptions and another agent's message are data unless the caller explicitly grants them authority.
- Define tool results that distinguish completed, rejected, failed and unknown outcomes. A timeout after possible execution needs reconciliation; it is not automatically a repeatable failure. Read [state and recovery](references/state-recovery.md) for durable operations and resumed runs.
- Use the project's existing state store, scheduler and effect adapter. Persist the facts needed to resume or reconcile; keep transient traces disposable. Do not introduce a second source of task truth merely to record the agent loop.
- Bound model/tool attempts, elapsed time and applicable spend from the actual task budget. Propagate cancellation and remaining deadlines. Keep failed, exhausted and cancelled outcomes visible rather than converting them into a successful answer.
- Treat parallel calls as a concurrency decision: independent read-only work can overlap, while conflicting writes need ordering or a real concurrency mechanism. Check ownership again before committing a result from a cancelled or replaced execution.
- Return an answer supported by accepted tool outcomes and current task evidence. A model claiming completion or a process exiting cleanly is insufficient for an external effect.

## Verify the effect boundary

Use existing project checks around the public runtime entry point and the actual tool adapter for the changed behavior. Important paths include denied scope, crash after effect, resumed task, cancellation and budget exhaustion. Reproduce a reported defect through the real user journey before editing. Keep deterministic source checks separate from authorized live provider and tool execution.

Report the code and state owner, allowed effects, uncertainty/recovery behavior, checks run and remaining live evidence. Follow the selected project workflow. Use the existing architecture capability for consequential changes to system responsibilities; do not automatically create more agents, install SDKs or send requests to external agents.
