---
name: blocked-agent-pr-handfix
description: Use when an agent PR is blocked; land the fix by hand.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [warden, merge-blocked, pr, hand-fix, worktree, verification]
    related_skills: [warden-blocked-items, warden-item-watch, agent-branch-recovery, agent-worktree-verification]
---

# Fixing a blocked agent PR on its own branch

## When to Use

A Warden item is in `merge_blocked` (or an agent-opened PR came back refused by
step-7 validation) and the finding is one small, verifiable edit. Not for a
finding that needs re-deriving the change, and not for a repo the episode itself
can still reach.

A `merge_blocked` item's PR is the carrier of work that is already sound: the
step-7 review refused *details*. When the finding is one small edit, the cheap
route is a hand commit on the PR's own branch — not a new `run`.

**Why a new `run` is the wrong tool here.** An implement episode's worktree is
cut fresh from the repository's **default branch** and its tier forbids remote
ops and touching another branch, so "fix it on top of `PR #n`'s head" is
*structurally* impossible: it answers `no_changes`. A re-dispatch therefore
re-derives the whole change as a **second PR** while the first lingers, and gets
its own review round for a one-line difference. Two routes exist for a fix that
belongs to an unmerged carrier: the owner merges first and the follow-up is
briefed from master, or you land the commit yourself — this skill.

## Procedure

1. **Read the finding off the item, not the card**, and check it against the code
   before believing it: `curl -s http://127.0.0.1:7735/items/<id>` → `item.note`
   carries `step-7 validation (blocked): <file:line> — <finding>`. Pull the file
   from the PR head (`gh api repos/<o>/<r>/contents/<path>?ref=<sha> -H 'Accept:
   application/vnd.github.raw'`) and read the named lines.
2. **Reproduce it against the pre-fix head.** The finding is real when you can
   make the shipped code produce the wrong verdict: mirror the pre-fix file into
   the layout the repo's test expects (`git show <sha>:<path> > <scratch>/<same
   relative path>`, copy the test beside it) and run the suite. A new test case
   that fails on the old file and passes on the new one is the proof — a test
   that passes on both proves nothing.
3. **Work in a detached worktree at the PR head**, never the live checkout:
   `git worktree add --detach .claude/worktrees/<name> origin/<branch>` — a
   repo-local worktree is what `make worktree-audit`/`worktree-prune` already
   knows how to reclaim.
4. **Land one commit**: the fix, its test case, and the doc line that described
   the old behaviour (a doc that now lies is part of the finding). Fold follow-ups
   into it with `--amend` rather than stacking commits — the repo's own rule.
   No attribution footers.
5. **Run the repo's own target for that area** (it may bundle lint/shellcheck
   ahead of the test — that is the point of using the target rather than the
   script). Then **push back to the same branch** and verify the read-back:
   `gh pr view <n> --json headRefOid,isDraft,mergeable` and a `gh api …contents`
   grep for a symbol only the new commit has.
6. **Mark the PR ready**: `gh pr ready <n>`. A **draft PR cannot be merged**, so
   leaving it draft turns "please merge" into a dead end — the common end state
   for a repo whose policy has no `autoMergePaths` (`dotfiles`, and every repo
   absent from `warden/config/triage-policy.json`'s `repos`), where the owner's
   merge button is the only merge gate that exists.

## Finishing when the repo auto-merges (or the card is already stale)

For a repo WITH `autoMergePaths` (`weatherorb`, `vps`, `homelab`, …) the loop
would have merged and deployed had step-7 passed, so the hand-fixer owns the
whole tail, not just the commit:

```bash
gh api repos/<o>/<r> --jq '{allow_squash_merge,allow_merge_commit,allow_rebase_merge}'  # pick an allowed method
gh pr merge <n> --rebase --match-head-commit <head-sha>   # makes it merge exactly what you verified
```

Then run the **policy-declared rollout** — `triage-policy.json`'s
`repos[repo].deploy` key maps to a closed argv in warden's
`scripts/clients/rollout.py` (`weatherorb-pull` = `git pull --ff-only` +
`make launchd-install` + `kickstart -k` of the KeepAlive tileserver/sync). A
merge alone leaves the running daemon on the old code: run the argv by hand, from
`~/SourceRoot/warden`, via
`python3 -c "import sys;sys.path.insert(0,'scripts');from clients import rollout;print(rollout.argv_for('<key>'))"`.
Finally `./scripts/warden close <event-id> --why …`: the loop has no merge
watcher, so a merged `merge_blocked` row sits on the board until its 168h
deadline unless you close it (`warden-item-closure`).

**A card can be stale by a whole hand-fix.** Before touching the branch, compare
the blocked transition's timestamp with the head's commit dates
(`gh api repos/<o>/<r>/pulls/<n>/commits`) and read the PR body for a
`## Post-review (hand-landed)` section. If the head is newer, a previous session
already made the edit — redo neither the commit nor the reproduction; the tail
above (merge, rollout, live proof, close) is the whole remaining job, and the
card keeps re-rendering its stale note because nothing syncs it to the branch.

## Pitfalls

- **The loop may already be revising — check `transitions` before you touch the
  branch.** A `merge_blocked` item is auto-revised by Warden itself (the
  transitions read `revision 1/2:`, `revision 2/2:`), and each revision opens a
  **new branch and a new PR while closing the blocked one** — so a hand commit
  landed without that check can end up on a branch that is already superseded, and
  the repo carries two carriers of one change. Read `transitions` and
  `dispatches` first; hand-fix only when the revisions are exhausted (the note
  then reads `Do this: …`) or when the loop cannot reach the code at all.
- **Verify the finding against the CURRENT head, not against the note.** The note
  is a snapshot written at one transition, and a revision can land the fix for it
  after the review ran — the same defect was reported as blocking while the head
  already carried both its fix and a test for the exact boundary, with a comment
  explaining it. So reproduce the finding on the head's code (`git show
  origin/<branch>:<path>`, or a worktree at the head) before writing anything, and
  read the boundary cases yourself rather than trusting the repo's suite alone:
  the sweep that decides it is small (`for OFF in -1 0 1 …` around the threshold,
  asserting the FAIL exactly where the value crosses it).
- **A mangled-looking literal in a rendered diff is usually output masking, not
  the file.** A 7-digit constant came back as `1****75` in `gh pr diff`, in
  `read_file` AND in a plain `sed -n` of the worktree — while the blob was intact.
  Before "fixing" text you only ever saw through a tool: compare hashes
  (`git rev-parse HEAD:<path>` against `/contents/<path>?ref=<sha>`'s `.sha`), and
  prove a string's presence with a computed boolean (`'*' in line`) rather than by
  eyeballing the rendering. A patch that leaves the tree identical (same
  `rev-parse <sha>^{tree}`) is a no-op: restore the head you pushed over instead of
  leaving a content-identical amend behind.
- **A `|| true` on a bookkeeping write is a silent-off switch.** A guard that
  persists state (a counter, a last-seen reading, a marker) and swallows the
  write's failure reports *healthy* while it can never fire again: no state file,
  no delta, and the run takes its first-run branch for ever. Assert the write and
  make its failure the check's own non-zero — and test the unwritable path, which
  needs no permission games: a regular **file** where the state *dir* belongs (or
  a directory where the temp file goes) fails the write on any host, as any user.
- **A repo whose test suite runs under `set -e` needs the guard, not the swallow.**
  Replace `write || true` with a guarded call (`persist … || { echo …; return 1; }`)
  — the failure stays non-fatal to the run while the component grades FAIL.
- **An amended commit must be force-pushed** (`git push --force-with-lease origin HEAD:refs/heads/<branch>`) — a plain push is refused as non-fast-forward, and the repo's amend rule makes amending the norm rather than stacking a fix commit on a branch whose review verdict already covers one head.
- **`mergeable: UNKNOWN` right after the push is not a refusal.** GitHub computes mergeability asynchronously: re-poll `gh pr view <n> --json mergeable,mergeStateStatus` a few seconds later — `MERGEABLE`/`CLEAN` plus the re-run check green on the **new** head sha is the read-back that proves the hand-fix landed. Confirm the new sha with `gh api repos/<o>/<r>/contents/<path>?ref=<sha> -H 'Accept: application/vnd.github.raw' | grep <new symbol>`.
- **Check the finding's own classification.** A review can report one blocking
  finding plus several `improvement`s; fix the blocker to unblock the merge and
  name the rest as open work rather than silently expanding the diff.
