# Probing a claimed defect

_Use when verifying a claimed code defect before acting._

A reviewer finding, an agent verdict, or your own hypothesis about a guard, parser or
matcher is a **claim** until you have run it. Probes cost minutes and no dispatch, and
they change what you write: an artifact carrying a measured reproduction pins the target,
while one restating the finding can be re-read as "the naive reading".

Reach for this when a finding is about to become work — a fix brief, a relayed
conclusion, an issue, or a "this is broken" claim to the user.

## Procedure

1. **Probe the exact revision the finding names — in a throwaway worktree.**
   `git fetch origin <branch>`, then `git worktree add --detach /tmp/<probe> <head-sha>`.
   A finding worded against a PR head confirms nothing on the live checkout, which is
   usually at the default branch with uncommitted edits.
2. **Import the branch's own module and call the function the finding names.** A
   re-typed copy of the matcher reproduces your reading of the code, not the branch's
   behaviour. Run it with the repo's own runtime (`bun run probe.ts`, `node`, `python`).
3. **Assert both directions in one run.** The case the finding claims is accepted, *and*
   the previous round's exploit still refused as a control: that pair shows a new hole
   rather than a broken harness.
4. **Size the input like production.** Guards carry their own size caps (anchor length vs
   body length, coverage fractions, retry budgets). A short fixture can be refused for
   being *too large* and read as "that class is closed". Scale past the cap and record
   the sizes you used.
5. **When a case is refused, find out WHICH rule refused.** Read the branch's own code
   path before writing the result down: the same input can be rejected incidentally by an
   unrelated cap that binds on your fixture. Name the rule, or drop the case.
6. **Clean up and hand off the numbers.** `git worktree remove --force /tmp/<probe>` —
   never probe in the live checkout other agents share. The result lands in the artifact
   as: literal input, the sizes, the observable output, and the control's outcome.

A copyable skeleton is in `templates/probe-skeleton.ts`.

## Pitfalls

- **Your own probe is the weakest evidence in the chain** — you chose its cases. A later
  review that finds the case you did not test is not being unfair; say in the artifact
  which dimension you varied and which invariants you held satisfied.
- **Do not vary an invariant the guard already checks.** A case that leaves a checked
  invariant violated exercises that check, comes back rejected, and reads as "the class
  is closed".
- **The same harness is the post-fix negative control.** Restore the pre-fix file from
  git, re-run, and show the new test rows fail — that is the evidence that a test
  exercises the hole rather than the new code.
- **A probe result is not a fix.** It belongs in the brief, the issue or the report as
  the reproduction; it never substitutes for the acceptance commands the repo owns.
