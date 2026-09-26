---
name: writing-workflow
description: Turn a short writing direction, supplied specifics, and a thesis or theme into a private, evidence-aware, approval-ready draft. Use for substantial technical documentation, code-adjacent language, project pages, arguments, essays, stories, and personal or cultural writing when form, claims, disclosure, voice authority, review, or explicit human approval may matter.
---

# Writing workflow

For a request to revise the supplied prompt itself, use `prompt-enhancer`; do not draft the work described by that prompt. For product documentation, use `author-product-docs` when installed. That capability owns documentation structure and behavior checks; this workflow retains any applicable authorial, disclosure and publication boundaries.


Provide one small front door from input to a private, evidence-aware draft.
Keep planning records and drafts private until the applicable approval decision is explicit.

## Small user interface

Accept this minimum input:

```yaml
direction: one to five short statements
specifics: facts, examples, scenes, or exact details to use
thesis_or_theme: desired answer, point, or narrative center
```

Optional fields are `form`, `register`, `audience`, `tone`, `disclosure`, and `avoid`.
Do not require the user to complete an internal schema.

## Establish authority

Identify the owning sources for:

- facts and technical state;
- claims, opinions, and thesis;
- voice and register;
- personal, employer, infrastructure, security, and third-party disclosure;
- repository instructions and content-type contracts;
- publication and approval.

Private authority may inform review without being copied into public repositories.
Current prose, templates, detector output, passing tests, and earlier summaries are evidence only when the owning authority says they are.

## Classify before drafting

Classify the content register and rhetorical form separately.

Supported registers:

- tutorial;
- how-to guide;
- reference documentation;
- technical explanation;
- architecture or decision record;
- code comment or docstring;
- CLI output or error;
- project page;
- technical essay;
- personal or cultural essay.

Supported forms are `argument`, `explanation`, `story`, `mixed`, and `operational`.
For mixed work, name `argument` or `story` as the primary form.

A story primarily asks the reader to experience what happened, what changed, or why a moment matters.
An argument primarily asks the reader to believe or do something because reasons and evidence support it.
Topic does not determine form.

## Ask only blocker questions

Play back one sentence naming the content class, primary form, governing claim or narrative center, and intended reader result.
Ask at most three focused questions when missing information would otherwise require invention or materially change the result.

Blockers include:

- unresolved opinion or thesis ownership;
- evidence too weak for the proposed claim;
- a story that lacks the events or details needed to draft honestly;
- disclosure state that is unknown or requires case approval;
- several materially different frames or primary forms;
- an approval class or public destination that cannot be determined.

Do not ask for information already supplied.
Do not manufacture options when one interpretation clearly fits.

## Stabilize the private brief

Build `EditorialBrief/v1` from `references/contracts.md`.
Do not draft until it records:

- register, form, and primary form when mixed;
- governing statement and its ownership;
- claims, evidence, scope, limitations, and disclosure where applicable;
- confirmed story material and details not to infer where applicable;
- voice and tone authority;
- approval class;
- blockers and draftability.

Opinions use `user_stated`, `user_approved`, `agent_proposed`, or `unresolved` ownership.
Only the first two may be written as the user's settled public position.
An agent may suggest a private thesis or theme, but it remains a proposal.

## Route by register and form

- Use `author-product-docs` when available for tutorials, how-to guides, reference, and technical explanations. If it is unavailable, report the missing capability when its documentation review is required; do not claim that review ran.
- Apply Minto's top-down discipline to technical, academic, and professional arguments and explanations: answer early, group support by real logical relationship, attach evidence and limits to the claims they qualify.
- Use `storytelling-narrative` for story-primary work.
- Use repository-specific contracts for architecture records, comments, docstrings, CLI language, errors, and project pages.
- Load private voice, opinion, taste, or boundary authority only when the content requires it.

Minto does not apply to stories.
Do not force personal or cultural arguments into a consulting register.
Do not make a neutral operational string sound like an essay.

## Draft privately

Draft only after the brief is stable enough for the requested form.
Use the shortest version that preserves meaning, evidence, qualification, and useful texture.
Prefer specific nouns and verbs, natural short paragraphs, only necessary transitions, and lists only for real parallel sets.

For personal or cultural material, preserve grounded details, reactions, humor, excitement, irritation, and fragments from the supplied source.
Do not manufacture personality, vulnerability, intimacy, sensory detail, or a professional lesson.

Place explicit placeholders only in private drafts and mark them as `{{PRIVATE_PLACEHOLDER: description}}`.
No unresolved private placeholder may enter public source.

## Review in order

Review the private draft in this order:

1. **Evidence and claims:** verify facts, claim basis, scope, limitations, and ownership.
2. **Disclosure:** confirm that each material use is public for this exact context.
3. **Structure and register:** apply the content contract and preserve the approved form.
4. **Contextual style:** review cadence, naturalness, precision, specificity, and earned tone.
5. **Surface pass:** run `rewrite-slop` conservatively without changing frame, claims, story sequence, or disclosure.
6. **Deterministic verification:** run `scripts/verify.py` against the private brief and applicable rule corpus.

Role ownership is explicit:

- a human or agent may draft privately from an approved brief;
- the named technical or domain owner verifies product facts, behavior, and technical claim evidence;
- The represented human owns personal meaning, beliefs, identity-bearing claims, private-boundary decisions, and disclosure about his life or voice;
- a designated contextual reviewer may advise on structure, register, and style but cannot approve the represented human's voice or beliefs;
- the deterministic checker reports conformance and review signals only;
- the represented human explicitly approves identity-bearing or opinion-bearing public writing, while the named domain owner may approve eligible delegated operational prose.

An implementation agent may assemble evidence and propose a disposition.
It may not review its own draft into authorial approval or satisfy domain-owner approval by assertion.

Write briefs, drafts and calibration records only to the caller-selected private location, outside the installed skill.

Detection is separate from enforcement.
Deterministic checks may establish schema, placeholder, punctuation, and rule conformance.
They cannot certify evidence grounding, privacy, editorial acceptance, taste, naturalness, truth beyond supplied evidence, approval, or that a piece sounds like its author.

## Public writing approval

Classify approval need as:

- `human_approval`: identity-bearing, first-person, bylined, personal, cultural, positioning, reputation, opinion, mentorship, or disclosure-bearing public content;
- `delegated_domain`: neutral technical or operational prose under a named domain owner;
- `generated_mechanical`: reproducible non-authorial output;
- `private_only`: briefs, drafts, source interviews, rejected examples, and calibration records.

Identity-bearing or opinion-bearing public writing stays a private draft until the represented human explicitly approves it.
An agent must not infer approval from silence, partial agreement, a previous draft, a passing check, its own review, or the absence of objections.
The public repository does not define how the represented human records or enforces that approval.
AFK integration may remain available for code and delegated technical artifacts when the owning repository permits it.
Do not move a private draft into a public source tree before the required human approval.

## Learn from rejection

Route rejection to the earliest affected layer:

- wording or cadence to private rewrite;
- thesis, theme, audience, meaning, or form to frame review;
- claims to evidence review;
- personal or sensitive material to disclosure review.

Record a private `CalibrationEvent/v1`.
Use a rejected draft as a negative example.
Use a corrected draft as a positive example only after explicit approval from the owning human or domain owner.
Do not automatically change identity authority from one rejection.

Read `references/contracts.md` for the small internal records.
Read `references/golden-corpus.json` when evaluating rules, registers, false positives, borderline cases, or exceptions.
