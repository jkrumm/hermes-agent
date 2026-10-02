---
name: pr-review-hardening
description: Harden a change through repeated adversarial review.
version: 1.0.0
metadata:
  hermes:
    tags: [review, hardening, pr, gates, adversarial, regression]
    related_skills: [warden-verdict-disposition, agent-pr-handoff, github-code-review]
---

# Hardening a change through repeated adversarial review

A change that must not regress — a parser, a matcher, a security-relevant gate —
is not finished when the tests pass. It is finished when independent reviewers
stop producing **reproducible** findings. This is the loop for that, plus the
discipline that keeps it from running forever.

## When to use

- The change touches a matcher, parser, or gate where an edge case is a
  correctness or security defect.
- The user asks for a change to be reviewed, hardened, or "made right" before merge.
- A dispatch pipeline runs a validation step you must satisfy before it will merge.

Skip for documentation, config, and changes whose failure mode is cosmetic.

## Procedure

### 1. Establish the gates before the first review

Run the repo's own gates and **record the numbers**: test count, typecheck, lint,
and any dead-code/complexity audit. That set is the invariant you must not
regress, and you re-run **all** of it after every fix batch — not just the tests.

### 2. Dispatch the review against the PR HEAD, not the base

Give the reviewer the head commit's diff. Reproduce every finding against a
worktree of the head.

**A probe that imports the base branch's module will "confirm" findings that are
not in the change at all.** Check the worktree out at the head before you touch
the code, or you will spend a round fixing a phantom.

### 3. Triage each finding: reproduce, then classify

Classify every finding as **real**, **unreproducible**, or **already disproven**,
and say which. A blocking finding can be factually wrong, and an adversarial
reviewer will re-raise the same disproven claim across several passes.

When a claim is wrong: do not edit correct code to appease it. Record in the
commit message that it was checked and why it is wrong, so the next pass does not
re-litigate it, and note intentional behaviour in the fix prompt.

### 4. Fix at the root, not at the case

When the reviewer names a structural fix — "rewrite this coherently instead of
patching each case" — that is a finding in its own right. Case-by-case patching
of a matcher produces a new edge case every round; the structural rewrite closes
the class. Prefer the rewrite.

### 5. Pin every fix as a regression test

Each real finding becomes a test row, including the **near-miss negatives** (the
input that must NOT match). A fix without its negative case gets re-broken by the
next round.

### 6. Re-run every gate, then re-review

Re-review is what proves the blocking list is actually empty — a locally green
suite is not that proof. Re-dispatch after each fix batch and read the new verdict.

### 7. Stop when the tail stops being real

An adversarial reviewer's edge-case tail is **unbounded**. Stop when the
remainder are unreproducible or cosmetic, and say so explicitly rather than
spending another pass. Report the count of passes and the real defects found —
diminishing returns is a reason to stop, not a reason to keep going silently.

## Pitfalls

- **A gate that audits only CHANGED files makes a file's pre-existing findings
  newly in-scope.** Editing a file can fail a repo's dead-code/complexity gate even
  when your diff is clean, because the gate's scope is the changed-file set, not the
  diff. Before "fixing" what it reports, prove which findings are yours by running
  the same gate on a pristine checkout of the base.
- **Keep your own new code under the gate's thresholds.** A new function over the
  complexity limit fails the gate exactly like an unused export does — split it into
  named helpers rather than arguing the threshold.
- **A file with a stray NUL byte renders as `Binary file not shown`.** The diff is
  then unreviewable (GitHub reads `.gitattributes` from the merge base, so adding
  `text` there fixes local `git diff` but not the PR view). Remove the NUL from the
  source — and re-check what it was separating, since a composite-key separator
  swapped for a space silently collapses distinct entries. `git diff --text`
  renders meanwhile.
- **A PR that resolves an issue must carry a closing keyword** (`Closes #N`). Where
  the issue tracker doubles as a work-intake queue, a merged-but-unclosed issue
  re-enters the queue as a fresh item and the work is done twice.
- **Re-read the PR body before merging.** A body written before the review rounds
  describes an earlier design — wrong module names, a superseded approach, an old
  test count. Update it so the merge record matches the code.
- **Shell backticks mangle a commit message.** Write the message to a file and use
  `git commit -F <file>` rather than an inline `-m` with backticks in it.
- **Check the PR against its open siblings, not just its base.** Several PRs on one
  repo each show `mergeable` against the base while colliding with each other;
  GitHub never tests them as a set. `git merge-tree --write-tree <mine> <other>`
  reports the collision with no checkout, and names the conflicting files.

## References

- `references/text-matching-edge-cases.md` — the defect classes that recur when
  hardening a URL/text matcher: encoding, Unicode, boundaries, parsing, output
  safety, dedup keys.
