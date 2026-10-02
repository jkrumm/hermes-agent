---
name: shared-checkout-concurrency
description: Use when another session may be editing the same checkout.
version: 1.0.0
metadata:
  hermes:
    tags: [concurrency, sessions, worktree, checkout, git, dedup, warden, agents]
    related_skills: [concurrent-card-dedup, warden-same-repo-serialization, agent-worktree-verification]
---

# Two sessions, one working tree

Sibling agent sessions — a duplicate Hermes lane on one Slack card, a watching cron,
a Warden episode, a foreground Claude Code session — share the **live checkouts**
under `~/SourceRoot`. The ledger dedupes work items; nothing dedupes a file. So a
twin can land the fix you are midway through, and a careless `git add -A` will sweep
their half-finished edit into your commit.

This skill owns the *file* half of the problem; `concurrent-card-dedup` owns the
*ledger* half (two items, one ask). Read this one when the card may already be in
flight, and that one before opening work of your own.

## Before you write anything for an inbound card

1. **Read the repo's history and its dirt in one shot:**

   ```bash
   git log --oneline -3 && git status --porcelain
   ```

   A commit you did not make, or a modification in a file you did not touch, is the
twin's. Judge it against when the work was handed out, not against your memory of the
session — your own earlier read is the thing that goes stale.

2. **A tool warning that a file "was modified by sibling subagent <id>" is the same
   signal, and a later one.** Re-read the file before patching: the content you
planned the patch from is gone, and a patch built on it silently reverts their change.

3. **Find the twin when you need its identity:** sessions are rows in
   `~/.hermes/state.db` (`sessions.started_at`, `title`, `last_activity_at`). Two rows
   with the same start second and the same inbound card title are one card handled
twice — a normal routing outcome, not an error to report.

## When the twin has already landed it

Stand down. Shipping the same fix twice costs a duplicate commit (or a second PR),
which is worse than the duplicate episode it was meant to be safe against.

- **Drop your own uncommitted edit** — `git checkout -- <file>`, or `git stash` if it
  is work worth keeping — and leave the tree clean for whoever is still running.
- **Never commit around a twin.** Stage explicit paths, never `git add -A`, while
  `git status` shows files you did not write.
- **Verify their change end to end, not their commit message:** run the thing (the
  job, the monitor, the endpoint, the produced file and its mtime), and check the
  artifact reached the state the user cares about — an empty
  `git log origin/master..master` means pushed, not merely committed locally.
- **Close the loop in whatever record owns the work** — item `close <id> --why` with
  the commit hash, the issue, the card — and say plainly that a second session landed
  it instead of implying you drove it.

## Pitfalls

- **A file you edited comes back `git status`-clean.** A sibling committed your working-tree
  edits together with theirs (`git add <path>` on a file both of you touched). Before
  re-applying anything, read the committed content (`git show HEAD:<path>`) and check your
  change survived — do not re-apply "to be sure", and do not assume the file reverted.
- **An uncommitted edit to a file a live daemon reads is already in effect.** Warden's
  `config/triage-policy.json`, a LaunchAgent plist, a Kuma config: the running process does
  not wait for a commit. Leaving such an edit uncommitted is not "work in progress", it is
  live behaviour that git contradicts. Commit it (or revert it) in the same turn you find it,
  and say which one you did.
- **Two sessions start in the same second.** "Nobody else has touched this" is a guess
  unless you looked; the `git log`/`git status` read belongs to starting the work, not
  to finishing it.
- **A twin's fix and yours can target different halves of one defect** (the producer
  and its consumer, the writer and the reader). Check what their change actually
  covers before assuming it subsumes yours — then decide once whether your half is
  still needed, rather than both of you editing the same file again.
- **Verifying is not re-landing.** If the artifact exists, confirm it and stop; never
  re-apply a change "to be sure".
- **A guard that reports another session's write is not a failure of yours.** Report
  the outcome (fixed, by whom, verified how), not the near-miss.
