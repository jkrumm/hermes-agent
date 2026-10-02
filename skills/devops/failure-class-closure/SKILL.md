---
name: failure-class-closure
description: "Use when a guard keeps getting bypassed each round."
version: 1.0.0
metadata:
  hermes:
    tags: [guard, checker, matcher, hardening, review, verification, fail-closed, probes, warden]
    related_skills: [pr-review-hardening, dispatch-brief-authoring, agent-worktree-verification, warden-lifecycle-gates]
---

# Closing a failure class

Round-by-round patching of a checker is how a matcher or guard acquires a new edge
case every review. When the reviews stop naming *cases* and start naming *classes* —
"it compares X, so Y slips past" — the fix is no longer a stricter check. It is a
contract change, plus a proof that the class is closed.

Use this when a guard/validator/matcher that must not regress has been blocked (or
re-blocked) by review, when the same defect family returns in a new shape, or when
you have to brief, verify or report that kind of fix. The review *loop* itself
(gates, triage of findings, when to stop) is `pr-review-hardening`; brief mechanics
are `dispatch-brief-authoring`; getting a worktree to run the suite is
`agent-worktree-verification`.

## Recognise the class before you fix it

The tell: N rounds, each closing the shape the previous review named, each leaving
every other shape unpoliced — because the protected set is re-derived *inside* the
checker from a per-shape pattern (a regex, a whitelist, a token list). Any whitelist
has a next member, so a reviewer that finds the class after this one is not being
unfair.

Say the round count and the shapes already closed out loud, and name the class they
belong to, before you propose round N+1. If you cannot name the class the last three
findings share, you will brief a fourth instance of it.

## The two moves that close a class

1. **Derive the protected set from the domain model the system already owns** — the
   parsed structure the pipeline actually produces, not a re-derivation at the check
   site. If that model is not reachable there, widen the call site in the same change
   rather than approximating it locally.
2. **Fail closed.** An input the checker cannot classify refuses the whole operation.
   Name the safe direction explicitly: an optional transformation degrades to its
   input, while a silent miss makes the product's public promise false. Ask which
   promise the checker exists to keep and make the code keep it for *everything* the
   docs call in scope.

Then keep one shared extractor/grammar for the whole checker. A correct path at the
new call site beside a stale one elsewhere is the same hole with a smaller door.

## Check an offered option before you offer it

When you hand an implementer a choice between two implementations, trace each
option's data through the call site first. A comparison of records the operation
never mutates is **tautologically green** — it observes nothing and burns the
episode's reasoning. The signal: the option's inputs are produced by code the change
does not touch.

## Tests must close the class, both directions

- Table-driven over **every** shape in the grammar, not just the one case the review
  named.
- A must-refuse row per shape **and** a must-accept row for the legitimate cases the
  change is supposed to keep working. A rule that refuses everything passes a suite
  that only pins what it knows.
- Show each refusing case **failing against the pre-fix code** (restore the file from
  git, run, quote the failures). Green on the new code alone proves nothing about the
  hole.
- **Measure the over-refusal cost** on a realistically sized input, and name the single
  point where the rule would be loosened. Only under-refusal gets reported as a
  defect; over-refusal that vetoes the legitimate majority is a silent no-op of the
  feature, which is its own bug.

## Prove the fix by replaying the defect

A green canonical set proves the branch compiles and its own tests pass. It does not
prove the reported defect is closed. In a worktree at the fixed head, against the
module's own exported entry point:

- Replay **every variant** the finding named, not only the first.
- Add a **must-accept control** from the same surface.
- **Size the input past the checker's own thresholds.** A guard carrying
  `min(<absolute>, <fraction> x length)` refuses on a small input for reasons that
  have nothing to do with the finding; that reads as "the class is closed", or blocks
  your must-accept control and looks like an over-refusal the change never
  introduced. Print the input size alongside the result.
- Probe the layers the diff did not touch: a refusal check and a
  sequence/comparison backstop can each be right alone and wrong together, and only a
  multi-edit or offset-shifting input tells them apart.
- If your own probe is the only evidence, say so. A reviewer who then finds your
  missing case is not being unfair.

## When the pipeline dropped the closing gate

An item that leaves an automated lifecycle keeps its **artifact** and loses its
**gate**: the PR or branch exists, and nothing reviews it, because the review step is
a separate job only the lifecycle creates. On this estate, concretely: an item flipped
to `merge_blocked` with a `deadline expired:` note while its episode was still
writing — the episode then finished and opened its PR, and no path re-adopts a
completed PR.

Before believing such a card, check the live job (`status: running` with a fresh
`lastActivityAt` and growing turn count is a working episode, not a blocker) and the
file mtimes in its worktree.

Recovery, in order:

1. Verify the artifact yourself (previous section) — the episode's "all tests green"
   is a self-report.
2. Close the stale card, naming the artifact: a clock artifact left open is phantom
   human work on the board.
3. Re-create the gate: open one fresh item whose brief **is** the review, and say in
   its `--why` that it exists because the lifecycle dropped the gate.
4. Report the rule that dropped it (function + line) as a control-plane fix. Where the
   control plane is itself dispatch-capped, that is the owner's hand change — do not
   hand-edit the control plane, and do not dispatch to it.

## Pitfalls

- **Do not re-brief the same instance.** A brief that restates the finding and asks
  for a stricter check is round N+1 of the same loop; state the contract change.
- **A structurally right option can be unwritable at that call site.** Check the call
  site's signature before offering it as the answer.
- **Over-refusal is not "safe" by default.** Degrading to the original input is safe
  for correctness but not for the feature.
- **A verdict's confidence is not verification.** "High confidence, all tests green"
  is the episode's own account; the probe replay is yours.
- **A superseded artifact must be resolved, not left beside its successor.** When a new
  branch contains the old one in full (`git merge-base --is-ancestor <old> <new>`),
  close the old PR and the items that name it, so exactly one artifact is in review.
