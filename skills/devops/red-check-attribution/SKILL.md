---
name: red-check-attribution
description: "Use when a red check may belong to the base, not the diff."
version: 1.0.0
metadata:
  hermes:
    tags: [checks_failed, ci, worktree, sideclaw, dispatch, verify, false-negative, pre-existing]
    related_skills: [agent-branch-recovery, fresh-worktree-test-lanes, warden, claude-dispatch]
---

# Attributing a red check: the base or the diff?

A change whose PR was withheld by a red check is **not** evidence that the change
is bad. Three different causes produce the same card, and only one of them is
about the diff:

| Cause | Tell | Where the fix goes |
|-|-|-|
| the diff broke something | the failing test/file is in the diff | the branch |
| the check is red on the **base** | the failing file is not in the diff at all | its own commit on master |
| the environment is missing something | fixture-shaped failures, config undefined | the environment, or the repo's test lanes |

The middle row is the one that reads as finished work and is not. Attribute
before concluding anything.

## Procedure

1. **Read which step failed, and whether the file it names is in the diff.**

   ```bash
   git diff --stat <base>...<ref>                 # what the change actually touches
   ```

   A `format:check` / `lint` / `typecheck` failure naming a file the change never
touched is a **base defect**. It withholds the PR from *every* episode in that
repo until it is fixed.

2. **Reproduce in a fresh worktree at the commit under test** — never in the live
   checkout, which has the gitignored state and tells you nothing.

   ```bash
   W=~/SourceRoot/.wt/<repo>-verify          # never /tmp — see Pitfalls
   git worktree add --detach "$W" <ref>
   ln -sfn ~/SourceRoot/<repo>/<gitignored-dir> "$W/<gitignored-dir>"
   ln -sfn ~/SourceRoot/<repo>/.env "$W/.env"              # Bun/Node repos
   ln -sfn ~/SourceRoot/<repo>/node_modules "$W/node_modules"
   cd "$W" && bun run format:check && bun run lint && bun run typecheck && bun test
   ```

   **A worktree with no `.env` reports far more failures than the diff causes** —
   link in every gitignored thing the suite needs, then re-run, and only then
   quote numbers.

3. **Run the same step in a second worktree at pristine `master`.** Red there too
   = pre-existing, and the item was mis-routed. Report both counts, not one.

4. **Fix a base defect on master, in its own commit** — run the repo's own
   formatter/linter over the offending file. **Never fold it into the episode's
   diff**: that diff is already correct and has to stay reviewable on its own.

5. **Then re-cut or rebase the branch** onto the fixed master. A branch cut before
   the master commit still carries the real change; re-running the episode is not
   the move.

6. **Say the attribution in the record.** In the close note: "the only red step was
   `<step>` on `<file>`, pre-existing on master and not in the diff". That sentence
   is what stops the next reader treating the item as unfinished work.

## Rules

1. **A red step naming a file outside the diff is never the diff's fault.** Verify
   it on pristine `master` before attributing it to the change.
2. **Do not weaken, skip or reformat a test to make a suite green.** A base defect
   is fixed at the base; a lane that cannot pass in a fresh worktree is deselected
   from the default run, not made to skip.
3. **One host-coupled failure survives every environment fix.** A test that reads
   the ambient `~/.gitconfig`, an ambient credential helper, or a live host service
   fails identically in both worktrees — compare against pristine `master` before
   calling it this item's problem, and report it as host-coupled rather than
   silently absorbed.
4. **A repo with no CI has no check-run to read.** `gh pr view --json statusCheckRollup`
   returns an empty/null entry, which is not a pass — verify locally and say the
   repo has no CI rather than implying checks were green.
5. **A repo with no `autoMergePaths` merges only on the owner's click.** Landing the
   fix does not land the PR; say which of the two you did.

## Pitfalls

- **Build the verification worktree under `~/SourceRoot/`, never `/tmp`.** colima
  mounts only `/Users` into its VM, so a `/tmp` worktree's bind-mounted paths
  resolve to nothing inside the container and the suite dies with a `Module not
  found` that reads like a broken diff and is purely a mount artifact.
- **A worktree's first test run is not evidence.** Missing `.env` and
  `node_modules` produce a pile of unrelated failures that collapses to the real
  one after the symlinks go in; quoting the first run misattributes the change.
- **`git worktree list` includes the agents' own worktrees.** A commit sitting in
  one is not on master, and a worktree parked at master's SHA with a clean status
  means that episode's work already landed.
- **A `checks_failed` card's note quotes the verdict's positive `summary`.** The
  card reads like finished work; the word `checks_failed` is the only signal that
  the PR was withheld. Never conclude from the note.
