---
name: dispatch-target-preflight
description: "Use when an implement dispatch must land a change."
version: 1.0.0
metadata:
  hermes:
    tags: [dispatch, implement, worktree, branch, preflight, warden, sideclaw, repo-state]
    related_skills: [claude-dispatch, warden, warden-lifecycle-gates, warden-verdict-disposition, agent-branch-recovery]
---

# Dispatch target pre-flight

An `implement` episode writes into a tree that is **not the one the finding was
made in**. Checking that the two match takes two commands and costs nothing;
skipping it costs an episode (10–40 min) that comes back having correctly
changed nothing. Run this before opening any implement run, and before
reporting that a repo's fix "will land".

This is the pre-flight. Reading a stuck item afterwards is
`warden-lifecycle-gates`; deciding what to do with a verdict is
`warden-verdict-disposition`.

## The two trees

| Tier | Base it reads/writes | Why |
|-|-|-|
| `investigate` | the live checkout's `HEAD` | the question is about *this* checkout |
| `implement` | a freshly fetched `origin/<default>` | the PR must not need a rebase |

Both are deliberate in sideclaw (`dispatch-git.ts`). The consequence is that in a
repo carrying **unpushed commits** the investigation can confirm a finding
against code the implement episode will never see. The failure is one-directional
and unmistakable once you know it: `outcome: no_changes`, `nextAction: human`, and
a verdict naming a file that is not in the tree it was given.

**The episode is right. It is not a defect, and re-dispatching reproduces it
exactly.** Report it as a repo-state fact.

## Procedure

1. **Find where the finding actually lives, across branches.**

   ```bash
   cd ~/SourceRoot/<repo>
   git branch -vv                                  # local branches + upstream + ahead/behind
   git log -1 --format='%h %ci %s' origin/<default>
   git log -1 --format='%h %ci %s' <default>
   ```

   A repo can carry an entire second line of development on a non-default branch
   (a redesign, a rewrite) while the default branch is still a much older
   generation of the project. If the file the verdict names exists only on that
   other branch, the change is real but **not applicable to the default branch** —
   say so and stop; do not open an implement run against the default branch.

2. **Measure the gap the episode will work across.**

   ```bash
   git status -sb                            # "[ahead N]" on the branch line
   git log --oneline origin/<default>..HEAD  # the commits the episode will not see
   ```

   Non-zero means the episode works against an older tree than the verdict. Either
   push first or make the change by hand — and say which, before spending an
   episode. A stale `origin/<default>` months behind the local tip is a standing
   condition, not a one-off: every implement run into that repo is affected until
   it is pushed.

3. **Check the repo can complete the chain at all.**

   ```bash
   python3 -c "import json;print(json.load(open('$HOME/SourceRoot/warden/config/triage-policy.json'))['repos'].get('<repo>'))"
   ```

   No entry (or no `autoMergePaths`) means the merge gate refuses every PR from
   that repo — *nothing merges without an explicit declared scope*. An implement
   run there produces a draft PR that is permanently the owner's to review. That
   is a legitimate outcome, but it is not "the fix landed", so do not promise it.
   Repos listed in `~/.claude/pr-required-repos.json` are refused for the same
   reason: a human review is required.

4. **Report the pre-flight, then open the run** — or don't.

   One line per finding: unpushed commits (count), where the finding actually
   lives (branch), whether the repo can merge at all. Then the recommendation:
   push, hand-fix, or dispatch.

## Reading a `no_changes` verdict

`outcome: no_changes` is a **correct** answer, not a failure, and it routes to
`needs_human` carrying the episode's own reason. Read the reason and classify it:

- *the file is not in this tree / this tree is a different generation* → the
  pre-flight above was skipped; the fix belongs elsewhere (another branch, or the
  repo needs a push).
- *the change is already present* → the work is done; the item is a stale card.
- *the change was refused for scope* (CI workflows, size ceilings, a
  credential-shaped added line) → relay the refusal; do not re-dispatch.

Never re-dispatch a `no_changes` verdict unchanged. Nothing about the second run
differs from the first.

## Pitfalls

- **Do not infer the dispatchable tree from the working checkout.** `git log` in
  the checkout you are sitting in shows `HEAD`; the episode sees
  `origin/<default>`. Compare the two explicitly.
- **A repo with a clean `git status` can still be far behind.** Clean means no
  *uncommitted* changes; it says nothing about unpushed commits. `git status -sb`'s
  `[ahead N]` is the signal, not the absence of modified files.
- **A finding is not portable across branches.** Before dispatching, confirm the
  file the verdict names exists on the branch the episode will cut from —
  `git show origin/<default>:<path>`. This one command prevents the most
expensive wrong dispatch.
- **Check whether the item is a test artifact.** Every repo here is public, so a
  third-party-shaped author is ordinary — and it is also how an end-to-end
  fixture is built. An item whose author is not the owner, or whose issue is
  already closed, may be a smoke test rather than work. Say so instead of
  reporting its finding as an outstanding defect.
- **Do not re-dispatch to unstick anything.** Every gate here reproduces the same
  refusal against the same wall and spends another episode.
