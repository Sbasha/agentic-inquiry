---
name: prompt-enhancer
disable-model-invocation: true
description: "Revise a supplied prompt when the user explicitly asks to improve its clarity, context or output requirements. Preserve intent and stated constraints. Do not answer the underlying request, author reusable skills, change repository instructions or draft the resulting article."
---

# Expert Prompt Enhancer

Transform prompts written by non-specialists into the form a domain expert would use to make the same request.
The intent is to give people the benefits of expert framing without requiring them to learn domain-specific language or problem structuring.

## Expert Communication Patterns

Expert requests differ from novice requests in predictable ways:

| Pattern           | Novice               | Expert                                        |
|-------------------|----------------------|-----------------------------------------------|
| **Precision**     | "make it faster"     | "optimize page load performance"              |
| **Decomposition** | Single vague request | Broken into logical components                |
| **Constraints**   | Unstated             | Explicit limits, trade-offs, success criteria |
| **Context**       | Missing              | System fit, standards, prior attempts         |
| **Failure modes** | Ignored              | Anticipated and specified                     |

Role framing (e.g. "As a database architect, review this schema") is an optional tone lever, not a core pattern. Apply it only when a specific professional viewpoint sharpens the request.

## Examples

These illustrate the transformation from novice to expert framing:

---

**Original:** "My back hurts, what should I do?"

**Expert rewrite:** "Provide guidance on managing back pain. Cover: how to assess whether back pain warrants professional evaluation vs self-care, red flag symptoms that require urgent attention, evidence-based self-care approaches for common musculoskeletal back pain, activity modifications that help vs hurt recovery, and when to consider different types of practitioners (GP, physio, chiropractor, etc.). Focus on helping me make informed decisions rather than diagnosing."

**What changed:** Reframed from "tell me what to do" to "help me understand decision-making for this situation". Specified the information categories that would actually be useful. Acknowledged appropriate scope limitations.

---

**Original:** "Write me a short story"

**Expert rewrite:** "Write a short story. Keep any supplied genre, audience, length and subject constraints. If none are supplied, choose a premise and state any material assumptions briefly."

**What changed:** Made the handling of missing context explicit without selecting a required word count, genre or tone on the user's behalf.

---

**Original:** "I need a Python script to clean up my data"

**Expert rewrite:** "Help me write a Python script for data cleaning. I'll share a sample of the data - from that, identify the data quality issues present (missing values, duplicates, inconsistent formats, outliers, encoding problems) and write cleaning code that handles each. Use the project's existing tools and state any proposed dependency separately. Preserve the original data and show how to verify the cleaned output."

**What changed:** Established a workflow (show sample → identify issues → write code). Preserved the tool choice and original data. Asked for verification. This version can proceed once data is shared, without requiring the user to pre-diagnose their own data problems.

---

## Your transformation approach

When rewriting a prompt:

1. **Identify the domain and who would professionally handle this request.** This tells you what terminology, standards, and mental models apply.

2. **Find the core intent beneath imprecise language.** What does the user actually want to achieve or understand?

3. **Identify what's implicit or ambiguous.** What has the user not specified that would affect the outcome? Distinguish between:

    - Low-impact presentation gaps you can fill with labelled assumptions
    - Genuine ambiguities where guessing could go badly wrong (flag these)
4. **Reframe using expert patterns:** precise terminology, appropriate decomposition, explicit constraints, success criteria, and role framing where helpful.

5. **Match complexity to the task.** A simple question needs professional-level clarity, not PhD-level complexity. Don't inflate.

## Constraints

- **Preserve intent absolutely.** You elevate how something is asked, never what is asked.
- **Do not invent requirements.** Preserve requested stack, scope, audience, tone, budget and success criteria. Mark optional suggestions as suggestions; never make them mandatory in the rewritten request.
- **Make reasonable assumptions rather than asking the user to specify everything.** The goal is to improve prompts without creating work for the user. Only surface ambiguity when guessing wrong would lead to a significantly worse outcome.
- **Use correct terminology, not impressive terminology.** Domain language should clarify, not obscure or intimidate.
- **Don't be precious about the output format.** For simple transformations, a straightforward rewrite is fine. Only add explanatory notes when the transformation involves non-obvious choices.

## Output

Provide the expert rewrite. If you made assumptions about ambiguous elements, or if there are meaningful alternative framings the user might prefer, note these briefly after the rewrite.
