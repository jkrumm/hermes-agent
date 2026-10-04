---
name: superseded-branch-triage
description: Use when an agent branch may be superseded by a newer one.
version: 1.0.0
metadata:
  hermes:
    tags: [agent-branch, superseded, pr, warden, merge-blocked, nul, refspec]
    related_skills: [agent-branch-recovery, agent-pr-handoff, warden-blocked-items, git-binary-diff-forensics]
---

# Is this agent branch superseded, or still the fix?

A blocked/superseded branch is not automatically work to re-dispatch. Agents cut
worktrees from the *current* master, so a later episode on the same repo often
re-derives the same change **and** fixes the findings that blocked the earlier one.
When that happens the old card is **superseded, not blocked** — closing it and
naming the surviving PR is the whole job, and dispatching a fresh episode is wasted
budget on a change that is already on a branch.

Answer this before you touch anything: **does another open branch on this repo
already carry this change?**

## Procedure

1. **List what is actually open**, in the repo, with branches and draft state:

   ```bash
   cd ~/SourceRoot/<repo>
   gh pr list --state open --json number,title,headRefName,isDraft,mergeStateStatus
   ```

   Two branches whose titles describe the same change is the signal. Drafts count —
   an implement episode opens its PR as a draft.

2. **Fetch both branches by full refspec** (a bare branch name may not exist as a
   remote-tracking ref):

   ```bash
   git fetch -q origin \
     'refs/heads/<old-branch>:refs/remotes/origin/old' \
     'refs/heads/<new-branch>:refs/remotes/origin/new'
   ```

   Re-run the fetch **in the same command** as anything that reads the refs — a ref
   created only by `fetch <src>:<dst>` can be gone by the next shell call, and
   `fatal: invalid object name 'origin/old'` on a ref you fetched earlier is that,
   not a missing branch.

3. **Compare the touched files as text.** `git diff --stat <old> <new>` can print
   `Bin N -> M bytes` when a file carries a raw NUL byte, which tells you nothing.
   `git show` still prints the whole blob, so strip the byte on the way through:

   ```bash
   git show origin/old:<path> | tr -d '\000' > /tmp/old.txt
   git show origin/new:<path> | tr -d '\000' > /tmp/new.txt
   diff -u /tmp/old.txt /tmp/new.txt
   ```

   Read the diff for the two things that decide supersession: the old branch's
   feature is present in the new one, and the specific findings that blocked the old
   one are addressed there.

4. **Check ancestry, but never rely on it alone.**

   ```bash
   git merge-base --is-ancestor <old-sha> origin/new && echo carries-it || echo re-derived
   ```

   `NO` is the common and *good* case: the new episode re-derived the change from
   master instead of branching off the old one, so the old commit is not an ancestor
   while the content still matches. Ancestry proves supersession; its absence proves
   nothing.

5. **Verify the surviving branch yourself** before you call the old card closed —
   cut a throwaway worktree at it, symlink `node_modules` from the live checkout,
   and run the repo's own targets (`bun test`, `bun run typecheck`, or the Makefile
   equivalents). The episode's own PR body is a claim; the test output is the proof.

6. **Close both sides, in this order:**

   - The Warden item: `./scripts/warden close <event-id> --why "<what blocked it, why
     it is superseded, which PR carries the fix, the verification numbers>"`.
   - The old PR: `gh pr close <old> --comment "Superseded by #<new>, which carries
     this change on top of the current master tip and fixes <the findings>."`
   - Mark the surviving PR reviewable: `gh pr ready <new>` (a draft cannot be merged
     and automated review skips drafts).

7. **Remove the throwaway worktree** (`git worktree remove --force /tmp/<repo>-v`) —
   a detached worktree left in `/tmp` keeps `git worktree list` dirty for the next
   session.

## Pitfalls

- **A `merge_blocked` note describes the *old* branch's review, not the repo's
  current state.** The card is only re-synced on a state change, so it can be hours
  stale while the fix is already on a newer branch. Read the live item and the open
  PR list before believing the card.
- **Do not re-dispatch to unstick a superseded card.** A fresh episode re-derives
  work that exists, and the merge gate refuses it for the same reason the old one was
  refused.
- **A missing `autoMergePaths` entry is a separate gate, not a defect.** On such a
  repo every PR is owner-merge-only however clean the validation — report it as one
  decision (add the scope, or merge by hand) and never merge past it.
- **A `Bin N -> M bytes` diffstat is a NUL byte, not a large change.** Strip and
  diff as text (step 3) before concluding anything about the size of the change.
- **A failed automated review is not a finding about the PR.** When the review job
  returns a needs-human verdict with an empty blocking list, the pipeline broke, not
  the diff — verify the branch yourself and file the pipeline defect instead of
  acting on findings that are not there.
