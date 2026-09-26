# Gate failure triage

Load this when a gate fails and its origin is uncertain. Preserve the failing
command, observed output, candidate identity and relevant environment before
changing the implementation or repeating the check.

## Establish the comparison

A failing file outside the diff does not establish a pre-existing failure.
Its dependencies, configuration, shared state or execution environment may
have changed. Inspect the failing user path and affected dependencies.

Use a recorded pre-change run when it identifies the actual starting
candidate and comparable command, dependencies and environment. Otherwise,
reproduce against that starting candidate in an isolated checkout when this
is possible within the existing authorization. In a dirty starting checkout,
HEAD alone is not that candidate. Preserve its source identity and existing
user changes rather than substituting a clean revision.

Do not stash, reset or discard the working candidate to make a comparison.
Do not commit user work or install dependencies merely to prepare a baseline.
If the required baseline or comparable environment is unavailable, report
its origin as unknown and state what prevents comparison. Reading an old
file can support a diagnosis; it does not prove that the same gate failed.

## Repair and evidence

Follow the project's gate and hygiene requirements. Repair failures within
the assigned scope and authorization, including confirmed earlier failures
when the governing project requires that. An earlier failure is not an
automatic waiver, and a task entry does not make a failing check pass.

When repair needs a consequential scope decision, missing capability or
additional authorization, preserve the observation and name that dependency.
Continue independent authorized work. Record the unresolved finding through
the existing task or evidence owner, checking for an existing entry first.
Do not create a second backlog or a new ordinary Markdown change log.

If the project permits an explicit gate exception, identify its authority,
affected check and limits. Keep the check reported as failed, blocked or
unrun as observed; do not turn the exception into a passing result.

After a repair, rerun the affected check and relevant preservation or failure
paths. Compare the complete observation, not just the failing filename or an
error-message prefix. Report any environment mismatch or unmeasured branch
that limits the conclusion.
