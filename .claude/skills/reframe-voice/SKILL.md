---
name: reframe-voice
disable-model-invocation: true
description: Propose and apply an evidence-led reframe when the user explicitly asks for reframe voice or wants to change a piece's governing question, thesis, narrative center, audience, stakes, or meaning. Do not use for ordinary copyediting or surface de-slopping.
---

# Reframe voice

Reframing changes what a piece means or how the reader is asked to understand it.
It is not a synonym for rewriting.

## Protect authority

Identify the current frame before proposing a new one:

- governing question;
- current thesis or narrative center;
- intended audience and reader outcome;
- claim scope and evidence;
- event selection, point of view, and disclosure posture;
- source of the opinion or meaning.

Never manufacture a belief, experience, personal scene, quotation, motive, or disclosure.
Mark a thesis or theme as `user_stated`, `user_approved`, `agent_proposed`, or `unresolved`.
Only the first two may be presented as the user's public position.

## Present the reframe

Show a compact frame comparison before drafting against a materially different frame:

```yaml
current_frame:
proposed_frame:
why_change:
evidence_preserved:
evidence_needed:
claim_or_story_scope:
disclosure_effect:
meaning_at_risk:
```

Ask for approval when the proposed frame changes the thesis, theme, causal account, audience, stakes, person centered, professional lesson, or disclosure role.
Do not infer approval from silence.

## Choose structure by form

For technical, academic, and professional arguments or explanations, use Minto's top-down discipline after the reframe is approved:

1. state the governing answer early;
2. group support by real logical relationship;
3. attach evidence and limitations to the claim they qualify;
4. give a consequential opposing case fair ground;
5. end with the decision, implication, or remaining uncertainty.

For stories, do not use Minto.
Use the supplied events, scenes, sequence, changes, and reflection.
Do not force a contrarian hook, opposing case, named framework, broader implication, call to action, or resolved moral.

For mixed pieces, name the primary form.
An embedded story may support an argument.
An embedded argument may remain light reflection inside a story.

Personal and cultural arguments still need a clear claim and earned support, but they do not automatically need a consulting register.

## Write tersely

- Name the point quickly.
- Prefer specific nouns, verbs, examples, and evidence.
- Add transitions only when the relationship is unclear.
- Use lists only for real parallel sets.
- Avoid slogans, staged reveals, forced analogies, decorative contrast, mandatory groups of three, and packaged conclusions.
- Preserve grounded humor, enthusiasm, irritation, and fragments when they come from the source.
- Stop when the piece has answered its question or completed its movement.

Read `references/techniques.md` when a proposed reframe needs help with evidence, objections, examples, or implications.
Read `references/example.md` for the frame-comparison format, not as a voice template.

## Review

Before returning a proposal or draft, verify:

- the new frame is explicit rather than hidden in sentence edits;
- the user owns or approved the governing claim or narrative meaning;
- sources support the claim as scoped;
- direct experience and observation are not presented as universal fact;
- the reframe did not increase disclosure without approval;
- the prose does not perform confidence, originality, humanity, or taste;
- the form contract remains intact.

After an approved draft, route any requested de-slopping to `rewrite-slop` as a surface pass only.
