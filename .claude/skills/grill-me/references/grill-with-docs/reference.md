<what-to-do>

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing. Asking multiple questions at once is bewildering.

If a _fact_ can be found by exploring the codebase, look it up rather than asking me. The _decisions_, though, are mine - put each one to me and wait for my answer.

Do not enact the plan until I confirm we have reached a shared understanding.

</what-to-do>

<supporting-info>

## Domain awareness

During codebase exploration, also look for existing documentation:

### Document authority

Find the project's actual glossary, context map and designated decision log from
its instructions and existing documentation. `CONTEXT.md` and `docs/adr/` are
examples, not required locations. Use the native sources and format. If no source
exists, keep proposed wording in the conversation until an appropriate document
is selected within the user's authorization.

## During the session

### Challenge against the glossary

When the user uses a term that conflicts with the existing project glossary, call it out immediately. "Your glossary defines 'cancellation' as X, but you seem to mean Y - which is it?"

### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term. "You're saying 'account' - do you mean the Customer or the User? Those are different things."

### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios. Invent scenarios that probe edge cases and force the user to be precise about the boundaries between concepts.

### Cross-reference with code

When the user states how something works, check whether the code agrees. If you find a contradiction, surface it: "Your code cancels entire Orders, but you just said partial cancellation is possible - which is right?"

### Update the selected glossary within scope

When terminology is resolved and glossary edits are authorized, update the selected native glossary. Otherwise return the proposed wording. [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md) is an optional example when the project has no format.

Keep current terminology in the glossary. Put historical rationale only in the designated decision log, and keep the specification and task sources authoritative for intended behavior and open work.

### Offer ADRs sparingly

Only offer to create an ADR when all three are true:

1. **Hard to reverse** - the cost of changing your mind later is meaningful
2. **Surprising without context** - a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off** - there were genuine alternatives and you picked one for specific reasons

If any of the three is missing, skip the ADR. Honor the project's decision-record policy and existing write authorization. Use [ADR-FORMAT.md](./ADR-FORMAT.md) only when no native format applies.

</supporting-info>
