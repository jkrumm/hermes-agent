---
name: review-round-convergence
description: "Use when one fix keeps failing review rounds."
version: 1.0.0
metadata:
  hermes:
    tags: [review, convergence, guard, matcher, invariant, hardening, rounds, fix]
    related_skills: [code-probe-verification, pr-review-hardening, dispatch-brief-authoring, warden-verdict-disposition]
---

# Converging a fix that keeps failing review

Symptom: independent reviews of the same change each return a *reproducible* blocking
finding, and each finding is a different instance of ONE class — typically a guard that
whitelists input shapes and is defeated by the next shape (a set vs. a sequence, then a
matching rule, then a token class the pattern never described). That tail is unbounded by
construction: another instance-patch reliably buys exactly one more round.

Use this when you are choosing the *next* fix for a change that has already been blocked
more than once on the same guarantee.

## Procedure

1. **Count the rounds by class, not by finding.** Read the blocking findings from the job
   store (all of them, not the latest card) and write one sentence: "every round so far has
   named a shape the whitelist does not describe". If that sentence is true, stop treating
   the findings as independent and close the class instead of the instance.
2. **Move the invariant's source of truth.** Derive the protected set from the structure the
   system already owns — the schema it is handed, the records the pipeline emits, the parsed
   model — instead of re-deriving "what counts" with a local pattern. The enumeration IS the
   defect; the missing shape is its symptom.
3. **Fail closed on anything unclassifiable.** Over-refusal is usually the safe direction when
   the pass is an optional rewrite and the caller keeps the original, whereas a silent miss is
   what makes the change's own published promise false.
4. **Treat the advertised guarantee as the acceptance criterion.** If the change publishes a
   claim — a warning string, a prompt sentence promising a user or a reviewer something — the
   code must enforce the whole of it, for every class that sentence names.
5. **Write the residual down, in code and in the brief.** An unlisted residual returns as the
   next blocking finding; an explicit one is settled and the review can move on.
6. **Verify the class with a probe before and after.** One probe showing the old exploit still
   refused and the new one accepted is what makes "we closed the class" a measurement rather
   than a claim — see `code-probe-verification`.
7. **Escalate instead of looping.** When the fix would change a product-level contract, a
   stage's cost on a critical path, or a file's structure, that is the owner's call: name it
   in the reply and keep it out of the fix round's scope.

## Pitfalls

- **The same defect class blocking twice means the direction was wrong, not the wording.**
  Rewriting the brief harder on the same pattern burns a round; change the invariant.
- **Count the attempts that never reached review before calling the blocks one class.** A revision
  budget is spent by every attempt — including one that fails the repo's own pre-push checks and
  pushes no PR. Two blocking verdicts can name two genuinely *different* guarantees (a swallowed
  state write, then a truncating threshold conversion) while a cap of two is exhausted by three
  attempts, one of them lost to a checks failure. Read every verdict from the job store: the same
  guarantee each round → close the class; different guarantees → the cap, not the fix, is the
  problem, and re-sizing it is the owner's decision rather than another code round.
- **Two rounds naming the same open discussion is a signal the decision is overdue**, not that
  the fix is failing. Surface it as a decision, not as another fix round.
- **A fix that only adds a token class is not a class fix.** If the next review can name
  another class in the same family, you have shipped the symptom.
- **Do not widen scope to pay for it.** The cheap related cleanups from the same review belong
  in the round; the structural refactors and cost/latency decisions it raises do not.
