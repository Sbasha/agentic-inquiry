---
name: rewrite-slop
description: Conservatively remove generic machine-writing residue from an existing draft without changing its frame, claims, evidence, disclosure, form, or voice authority. Use when the user explicitly asks to de-slop, humanize, or remove AI tells from supplied text, or as the final surface pass in an approved writing workflow.
---

# Rewrite slop

Treat this as surface editing, not authorship, detection, or structural review.
Preserve the draft's meaning, governing question, thesis or narrative center, claim scope, evidence, event selection, point of view, disclosure posture, intended reader outcome, and deliberate form.
Do not call prose AI-generated merely because it contains a familiar pattern.

## Establish the protected frame

Before editing, identify:

- rhetorical form: argument, explanation, story, mixed, or other;
- register and audience;
- source authority for voice, claims, and disclosure;
- facts, quotations, citations, code, names, dates, numbers, and examples that must remain exact;
- intentional fragments, repetition, terms of art, and structural choices.

If changing the text would alter any protected element, stop and route the change to reframing, evidence review, or disclosure review.
Do not hide a product, architecture, or claim problem with smoother prose.

## Remove technical residue

Remove or repair only artifacts whose intended disposition is clear:

- model-specific citation tokens and attachment markers;
- LLM-provider tracking parameters in URLs;
- malformed JSON attribution tails;
- decorative Unicode that does not carry meaning;
- the em dash character, using punctuation that fits the sentence;
- explicitly marked private placeholders before public release.

Do not silently remove an ambiguous bracketed phrase, source marker, quotation, or placeholder.
Flag it when its intended value is unclear.

## Review contextual signals

Treat these as review signals, not proof of authorship and not automatic deletion targets:

- chat residue such as praise, progress narration, or offers to do more;
- vague abstractions and self-praising adjectives;
- filler transitions and empty scene-setting;
- decorative negation and contrast;
- slogans, rule-of-three packaging, staged drama, and pull-quote sentences;
- anonymous authority, exaggerated source counts, or significance unsupported by the paragraph;
- repetitive cadence, synonym cycling, summary closers, and unnecessary restatement;
- fragments inserted only for punch.

Keep a signaled pattern when it is accurate, natural in the register, or required by the form.
The correct question is whether the passage earns the pattern, not whether the pattern exists.

## Preserve form

For technical, academic, and professional arguments, preserve an intentional Minto structure: answer early, grouped support, evidence and limits attached to the claims they qualify.
Do not treat answer-first structure, clear headings, or real parallel groups as slop.

For stories, preserve sequence, scene, point of view, withholding, turn, and ending when they are supported by the source material.
Do not move the conclusion to the front, manufacture a lesson, or convert the story into an argument.

For mixed work, preserve the approved primary form.
Do not expand a bounded story into a dramatic hook or flatten it into a proof point.

## Rewrite conservatively

- Prefer specific nouns and verbs.
- Use the shortest version that preserves meaning, qualification, and useful texture.
- Use short paragraphs when the thought is short.
- Add transitions only when the relationship would otherwise be unclear.
- Keep lists only for genuinely parallel items.
- Preserve the source writer's natural fragments, humor, enthusiasm, irritation, and repetition when they are earned.
- Remove contempt, motive claims, and performed certainty unless the source and evidence support them.
- Keep direct quotations, code, citations, and source-controlled terminology exact.

## Verify

Inspect the result against these questions:

- Did any fact, claim, example, quotation, citation, or scope change?
- Did the governing question, thesis, narrative center, reader outcome, or disclosure posture change?
- Did an answer-first argument become a staged reveal?
- Did a story become an argument or acquire an invented lesson?
- Did the edit remove an intentional fragment or add fragments for effect?
- Did any chat residue, filler, artificial symmetry, slogan, or unsupported significance remain?
- Did the edit add connective prose the reader does not need?
- Does the output contain the em dash character or an unresolved private placeholder?

If the input is already clean, return it largely unchanged.
Over-editing is a failure.

## Output

Return only the rewritten text unless the user asked for review notes.
Do not claim that the pass certifies taste, authorship, truth, evidence, disclosure, or publication approval.
