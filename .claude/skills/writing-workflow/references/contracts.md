# Writing workflow contracts

These records are private workflow interfaces unless a field explicitly belongs in approved public source.
Keep private authority, raw source material, reviewer identities, and calibration history out of public repositories.

## `WritingRequest/v1`

The user may supply only `direction`, `specifics`, and `thesis_or_theme`.
The agent may derive the remaining fields and ask at most three blocker questions.

```yaml
schema: WritingRequest/v1
request_id: stable-private-id
direction: []
specifics: []
thesis_or_theme: ""
form: argument | explanation | story | mixed | operational | decide
register: optional-register
audience: []
tone: []
disclosure: []
avoid: []
```

## `EditorialBrief/v1`

```yaml
schema: EditorialBrief/v1
request_id: stable-private-id
content_class: public_authorial | public_operational | generated_mechanical | private_only
register: tutorial | how_to | reference | technical_explanation | architecture_decision | code_comment_docstring | cli_output_error | project_page | technical_essay | personal_cultural_essay
rhetorical_form: argument | explanation | story | mixed | operational
primary_form: argument | story | null
governing_statement:
  text: ""
  ownership: user_stated | user_approved | agent_proposed | unresolved
claims:
  - id: claim-1
    text: ""
    basis: verified_fact | direct_experience | observation | inference | judgment | working_hypothesis | aspiration | speculation
    evidence_refs: []
    scope: ""
    limitations: ""
    disclosure: public | review_required | reserved | private
story_material:
  confirmed_events: []
  confirmed_details: []
  remembered_dialogue: []
  details_not_to_infer: []
voice_authority: []
approval_class: human_approval | delegated_domain | generated_mechanical | private_only
disclosure_state: public | review_required | reserved | private
blockers: []
draftable: false
```

For an argument or explanation, the governing statement must be `user_stated` or `user_approved` before human-approved public release.
For a story, an agent-proposed narrative center may support a private draft, but it must not be represented as the user's settled meaning before approval.
For mixed work, `primary_form` is required.

## Public writing approval boundary

`human_approval` is a routing classification, not a public approval protocol.
Identity-bearing or opinion-bearing public writing stays private until the represented human explicitly approves it.
An agent must not infer approval from silence, partial agreement, its own review, or deterministic verification.
The public repository does not define how the represented human records or enforces approval.

## `RuleFinding/v1`

```yaml
schema: RuleFinding/v1
rule_version: stable-rule-version
applicability: []
scope: exact-span-or-field
evidence: ""
enforcement_level: hard_failure | review_signal | contextual_judgment
judgment_route: deterministic | domain_owner | style_reviewer | exact_author
exception: null
disposition: open | accepted | false_positive | excepted | fixed
```

A detector reports a finding.
Policy decides enforcement.
Do not silently change a rule's meaning under the same version.

## `CalibrationEvent/v1`

```yaml
schema: CalibrationEvent/v1
request_id: stable-private-id
rejected_version: 1
feedback: exact-user-feedback
affected_layer: wording | structure | form | claim | evidence | disclosure | approval
model_change: ""
negative_example_ref: private-ref
approved_replacement_ref: null
```

Add an approved replacement reference only after explicit approval from the owning human or domain owner.
One rejection does not automatically rewrite durable identity authority.

Golden-corpus cases are synthetic rule expectations for calibration and testing.
Each case records its register, rhetorical form, disposition, and calibration authority.
Synthetic cases use `synthetic_system_expectation`; examples that preserve a direct user judgment must use `direct_private_calibration` and remain private when their source is private.
An `approved` disposition in that corpus is not publication approval for the example text.
