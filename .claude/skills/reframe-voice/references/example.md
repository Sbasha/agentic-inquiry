# Reframe comparison example

This is a synthetic process example, not a voice template and not publishable copy.

## Input

The supplied draft argues that a team needs a larger model because one benchmark score is low.
The available evaluation shows that most failures come from missing repository context, while model capability remains one unresolved factor.

## Frame comparison

```yaml
current_frame: A larger model will fix the benchmark.
proposed_frame: The benchmark cannot support a model decision until context failures and capability failures are separated.
why_change: The current claim exceeds the evaluation evidence.
evidence_preserved:
  - the observed benchmark score
  - the failed cases and their traces
evidence_needed:
  - a controlled comparison with context held constant
claim_or_story_scope: one benchmark and one repository fixture
disclosure_effect: none
meaning_at_risk: The reframe changes the recommendation from selection to further evaluation.
```

## Approval boundary

The proposed frame requires approval because it changes the governing recommendation.
After approval, a technical argument can lead with the new answer, group the context and capability evidence separately, and end with the next decision gate.
Before approval, the agent may present this comparison but may not rewrite the piece as though the user already owns the new conclusion.
