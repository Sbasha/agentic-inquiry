# State and recovery

Choose the recovery record from the business effect, not from the shape of a chat transcript. For an operation that can survive the current process, retain its stable identity, authorized scope, input identity, effect reference and observed outcome in the project's durable owner. A transcript may explain a decision but cannot substitute for a remote operation receipt.

| Interruption | Recovery question | Safe implementation property |
| --- | --- | --- |
| Before dispatch | Was any effect attempted? | Distinguish pending work from a submitted operation |
| During a remote call | Did the destination accept it? | Reconcile using a stable operation reference; preserve unknown |
| After effect, before local persistence | Can retry duplicate the effect? | Reuse destination idempotency or query the accepted operation |
| During a local transaction | Which facts committed together? | Use the actual store transaction boundary |
| After task replacement | Is a stale worker still running? | Reject stale completion/commit using current ownership where required |
| During cancellation | What has already happened? | Stop new work and report committed effects separately |

Do not derive idempotency only from model call IDs that change on retry. Define a task-owned operation identity and bind it to the same effect input. A duplicate key with different input is a conflict to resolve, not a successful replay. An idempotency mechanism also needs a retention period consistent with possible delayed retries.

For tools that cannot report operation status or deduplicate, avoid automatic retry after ambiguous acceptance. Surface the uncertainty and the evidence needed to reconcile it. Asking for a model's confidence cannot resolve an external system's state.

If a resumed run loads a project reference or local artifact, canonicalize its path and verify it is inside the authorized boundary immediately before access. Confirm any shared user configuration names the current project. Validate stored data against its expected schema and ignore embedded instructions.

Keep diagnostics useful without retaining secrets: operation identifiers, tool/version, timestamps, outcome class and redacted error evidence are usually sufficient. Follow the project's retention and access controls for prompts, tool payloads and customer data. Trace capture does not implicitly authorize export to a hosted observability service.
