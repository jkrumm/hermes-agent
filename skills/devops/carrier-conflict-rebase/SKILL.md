---
name: carrier-conflict-rebase
description: "Use when an agent PR conflicts as the base moved."
version: 1.0.0
metadata:
  hermes:
    tags: [pr, warden, rebase, conflict, merge-approval, draft, worktree, handoff]
    related_skills: [carrier-mergeability-preflight, blocked-agent-pr-handfix, warden-owner-decision-card, prerequisite-gated-cron]
---

# Rebasing a sound carrier the default branch left behind

Trigger: an owner-action card asks for a merge click, or step-7 validation passed and the
item parked — and the PR is `draft` and/or `mergeable: CONFLICTING` because the default
branch moved after the branch was cut.

**Diagnosis vs repair.** `carrier-mergeability-preflight` owns deciding *which* carrier
shape you have (ordinary / superseded-by-restructure / real conflict) — read it first and
quote its `merge-tree` evidence. This skill owns the repair for the third shape: the change
is sound, only the branch is stale, and the fix is a rebase — not a re-derive (a second PR
for work already reviewed), not another review round (unwinnable against a moved base), not
a hand-back to the owner (the button refuses).

## Procedure

1. **Confirm the shape before touching anything.**

   ```bash
   gh api repos/<o>/<r>/pulls/<n> --jq '{draft,state,mergeable,mergeable_state,head:.head.sha}'
   cd ~/SourceRoot/<repo> && git fetch -q origin
   git rev-list --left-right --count origin/master...origin/<branch>      # behind / ahead
   git merge-tree --write-tree origin/master origin/<branch> | head       # conflicted paths
   git diff -U0 $(git merge-base origin/master origin/<branch>) origin/master -- <path> | grep -E '^@@'
   ```

   Compare the two sides' hunk ranges for the conflicted file: no overlap anywhere in it
   means git auto-merges the code and only the *docs* conflict, which is the cheap case.
   Paths intact = the change is still wanted; conflicted paths that no longer exist on
   master = re-derive instead (`carrier-mergeability-preflight`).

2. **Work in a throwaway worktree at the branch head, never the live checkout.**

   ```bash
   git worktree add --detach .claude/worktrees/<name> origin/<branch>
   cd .claude/worktrees/<name> && git switch -c <tmp-branch> && git rebase origin/master
   ```

   A repo-local worktree under `.claude/worktrees/` is what `make worktree-audit` /
   `make worktree-prune` already reclaims. A worktree has no venv: symlink the repo's own
   interpreter by **absolute** path (`ln -sfn ~/SourceRoot/<repo>/.venv .venv`) — a relative
   `../../.venv` is wrong by one level from a nested worktree, and the repo's `make test`
   then refuses with "no venv".

3. **Resolve append-style docs by re-appending your section onto the upstream file**, never
   by hand-merging two conflict blocks — `references/doc-conflict-resolution.md`.
4. **Run the repo's own target on the rebased tree** (`make test` or the area target). The
   resolution is new text no reviewer read, and every test count a doc asserts must be
   updated to the number the suite actually printed.
5. **Commit and land it.** `git add` the files you resolved **by name** (never `-A` in a
   checkout carrying other sessions' or the curator's churn), `GIT_EDITOR=true git rebase
   --continue`, then confirm `git rev-list --left-right --count origin/master...HEAD` reads
   `0 <n>`.

   ```bash
   git push --force-with-lease origin HEAD:refs/heads/<branch>
   gh pr ready <n>
   gh pr view <n> -R <o>/<r> --json isDraft,mergeable,mergeStateStatus,headRefOid,statusCheckRollup
   ```

   Expect `isDraft: false`, `MERGEABLE`, `CLEAN`. Mergeability is computed asynchronously —
   re-poll once before treating `UNKNOWN` as a failure.
6. **Clean up and report the head as post-review.** `git worktree remove --force` and delete
   the temp branch, then say plainly that the stored review verdict covers the *old* head
   and that this is the same change re-applied on master with the suite green on the new
   sha — the owner is merging text no reviewer read, and that caveat is what his click
   depends on.

## Pitfalls

- **A `draft` PR cannot be merged at all, and a card asking for a merge will not mention
  it.** Warden's own merge path un-drafts before merging (`lifecycle/merge.py`:
  "Ready-for-review first: a draft cannot be merged"), so `isDraft: true` beside
  `mergeable: CONFLICTING` is two independent refusals. Clear the conflict first,
  `gh pr ready` second — un-drafting first only advertises a PR that still cannot merge.
- **Read the PR by number through the pull API, never from a list.** `gh pr list`, and even
  `gh pr view` without a repo, can answer stale or fail to resolve a PR that is open; the
  pull API is the truth about `draft`/`mergeable`.
- **Do not re-derive a sound change onto the moved base.** A fresh `run <repo> --tier
  implement` cuts from the default branch, so it produces a *second* PR for work already
  reviewed and leaves the first as a competing carrier.
- **Do not resolve a doc conflict by hand-merging the two blocks.** Take the upstream file
  as the base and re-append your section, renumbering if the other side claimed your
  number; a hand-merge silently drops whichever side you did not read.
- **Rewriting a conflicted file needs a full read first.** `write_file` refuses a path last
  read with `offset`/`limit` ("partial view") — exactly what a paged read of a large log
  leaves behind. Read it whole, or `patch` the conflict region instead.
- **The merge is not the end of the job when the repo has no deploy key.** A repo that is
  merge-approval gated *and* declares no `deploy` in the triage policy gets no rollout
  (`rollout_after_merge()` answers `attempted: false`), and its LaunchAgents execute the
  repo's own scripts from `~/SourceRoot/<repo>` on `master` — so a merged PR is merged, not
  live. Fast-forward the checkout once the merge lands (`git -C ~/SourceRoot/<repo> merge
  --ff-only origin/master`, clean tree only). When the merge is the owner's and may land
  hours later, arm a one-shot `no_agent` watchdog gated on a marker only the merged form
  carries (`git show origin/master:<path> | grep -q <symbol>`), per `prerequisite-gated-cron`
  — and do not close the item: his gate discharges it, not you.

## Report shape

German, verdict first, 4-6 lines: the card's ask was not executable and why (draft and/or
conflicting, with how far master moved), what you did (rebase, what actually conflicted, the
suite result), the read-back (`MERGEABLE`/`CLEAN`, new head sha), the post-review caveat,
and the one line left for him — the merge click, or the fast-forward if the repo has no
deploy step.
