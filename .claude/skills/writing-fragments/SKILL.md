---
name: writing-fragments
disable-model-invocation: true
description: Capture private raw writing material such as claims, scenes, observations, lines, questions, and half-thoughts before choosing a structure. Use when the user asks to collect fragments, develop raw material, or preserve noticings for later writing.
metadata:
  source: Inspired by https://github.com/mattpocock/skills
---

# Writing fragments

Capture useful raw material without turning it into an outline, argument, story, or public draft.
Fragments are private editorial capture by default.
Never place the file in an approved public content source unless the user separately approves promotion through the owning workflow.

## Start simply

If the user did not provide a path, ask once where to keep the private fragment file.
Confirm that the location is private editorial capture rather than a public source tree.

On first write, add one H1 working title and the first fragment.
Do not add frontmatter, a table of contents, a date, a taxonomy, or a proposed structure.
Capture useful material from the initial request rather than making the user repeat it.

## Ask focused questions

Ask one question at a time when a question will surface specific material.
Prefer questions about the exact claim, moment, observation, reaction, example, contradiction, image, or unresolved thought.
Do not interview relentlessly, perform therapy, or press for more personal detail than the writing requires.
Respect disclosure boundaries even though the file is private.

Minto, story frameworks, and final register selection are out of scope.
Claims and scenes may coexist without being reconciled yet.

## Preserve provenance

A fragment may be:

- a user statement or close paraphrase;
- a direct quotation or remembered line;
- a claim with a short basis;
- a scene or vignette;
- an observation, question, complaint, joke, or half-thought;
- an agent proposal clearly marked as a proposal.

Do not present an agent-created sentence, opinion, memory, or interpretation as the user's language.
Prefix agent proposals with an HTML comment:

```markdown
<!-- source: agent-proposal -->
```

User material may use `<!-- source: user -->` when provenance would otherwise be unclear.
Preserve direct quotations exactly and mark uncertainty around remembered wording.

## File format

```markdown
# Working title

<!-- source: user -->
A first fragment lives here.

---

<!-- source: agent-proposal -->
A possible line or connection for the user to accept, reject, or revise.
```

Separate fragments with a horizontal rule.
Use no headings inside the body.
Keep the order of capture unless the user asks to reorganize it.

## Writing rhythm

Before every write, reread the file and preserve the user's edits, deletions, and ordering.
Append without asking for approval for each fragment.
Mention additions briefly without interrupting the conversation with repeated save prompts.

Edit, merge, move, or remove a fragment only when the user asks.
Do not polish the whole file into one cadence.
Fragments may remain terse, incomplete, contradictory, or unresolved when that is their value.

## Handoff boundary

When the user is ready to write, hand the private material to the owning writing workflow.
The later workflow must still classify form, stabilize claims and evidence, review disclosure, draft privately, and obtain the required approval before public release.
Fragment capture itself proves none of those gates.
