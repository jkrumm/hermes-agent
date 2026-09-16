---
name: warden-blocked-items
description: Use when a Warden card needs a human (merge_blocked).
version: 1.0.0
metadata:
  hermes:
    tags: [warden, merge-blocked, needs-human, dispatch, review, validation, triage]
    related_skills: [warden, warden-digest-triage, claude-dispatch]
---

# Warden items waiting on a human

`needs_human` and `merge_blocked` are the loop *stopping*, not failing — each has
exactly one correct next move and most of them are not "retry the thing".

Reading Warden's state is the `warden` skill; the daily digest is
`warden-digest-triage`; **this** is what to do with a card that needs a person.

## Procedure

1. **Read the live item, never the card.** The card is a snapshot; the reminder
   path re-posts it unchanged (first reminder at `DEFAULT_NEEDS_HUMAN_REMINDER_HOURS`,
   a second and final one at 3× that, never a third), so a reminder is not new
   information. Check whether the work already moved before relaying the ask.

   ```bash
   curl -s http://127.0.0.1:7735/board
   curl -s http://127.0.0.1:7735/items/<eventId>   # item + every dispatch + transitions
   ```

2. **Read the ledger through warden's own venv python**, never the `sqlite3` CLI
   (macOS `/usr/bin/sqlite3` has no `-uri`, so it takes `file:…?mode=ro` as a
   literal filename and dies `unable to open database file (14)` — which reads
   like a missing ledger):

   ```bash
   cd ~/SourceRoot/warden && .venv/bin/python3 -c "
   import sqlite3
   c = sqlite3.connect('file:/Users/jkrumm/.warden/warden.db?mode=ro', uri=True)
   c.row_factory = sqlite3.Row
   for r in c.execute('SELECT event_id,state,repo,note,implement_job,validation_job,pr_url,reminder_count FROM triage_items WHERE state IN (?,?)', ('needs_human','merge_blocked')):
       print(dict(r))
   "
   ```

   `item_transitions` carries the whole chain with the note at each hop;
   `dispatches.validation_status` is `confirmed` / `blocked` / `needs_human` /
   `error` and is what the merge gate actually reads.

3. **Classify the block, then take the one matching action.**

| State and note | What it actually is | Action |
|-|-|-|
| `merge_blocked`, `step-7 validation (blocked): <file:line — finding>` | the review refused this PR | open a **new** `run <repo> --tier implement` item (below) |
| `merge_blocked`, `merge refused: … requires a human pull-request review` | repo is on the human-review list | owner merges by hand — not a Warden defect |
| `merge_blocked`, `no_changes` / `diff_refused` / `branch_no_pr` / `pr_failed` | the episode produced no artifact | re-run only with a **changed** brief |
| `needs_human`, `investigation concluded implement, but repo '<r>' is capped at tier '<t>'` | a policy ceiling, not a bug | the fix is a code change no dispatch can make — hand it to the owner |
| `needs_human`, `implement <job>: <summary>` with `nextAction: human` | the episode itself asked | relay the ask, do not re-dispatch |
| `needs_human`, `schemaVersion N, warden expects M` | pin-vs-server drift | check `make check-schemas`; the episode's work often already landed |
| `needs_human`, `step-7 validation (needs-human): Review ran N reviewers but synthesis failed to serialize a structured verdict` | the review pipeline broke, not the PR — see below | verify the branch yourself, close the item, file the pipeline defect |

**The synthesis-salvage card carries no findings — read `result.discussions`.** The
review job's verdict is `outcome: needs-human` with `blocking: []`, and its
`discussions[0].message` is supposed to hold the raw synthesizer text. Check its length
before believing the prose: when the synthesis session exits non-zero, sideclaw's
`classifyExitFailure` branch never sets `rawText`, so the message degrades to the
constructed error (`Session exited with code 1 (success)`) and the "findings were NOT
lost" claim is false. There is nothing to act on, so do not open a fix item — run the
repo's own `bun test` / typecheck against the PR branch in a throwaway worktree, close
the card naming the pipeline defect, and file it on `sideclaw` (`review.ts` salvage
branch + `classifyExitFailure`).

4. **Report one line per finding.** What the block is, the mechanism, what you
   did about it, and the single decision that is genuinely the owner's. German,
   verdict first, no PID/log dumps unless he asks.

## The fix path for a blocked PR

`merge_blocked` means the *validation* refused, so `warden merge <job-id>` exits 4
by construction (`merge_gate_check()` refuses any `validation_status != 'confirmed'`).
Do not run it, and do not report its refusal as a finding. The working path is a
new item whose brief carries the findings:

```bash
~/.hermes/scripts/hermes-cc.sh run <repo> --tier implement --wait --json \
  --origin-channel "$SLACK_CHANNEL" --origin-thread "$SLACK_THREAD_TS" \
  --why "<why this is a bounded fix>" <<'BRIEF'
<PR number/branch/head sha> implements <issue>. Warden's step-7 review blocked it
with N findings. Fix them ON TOP OF THAT BRANCH (cherry-pick or merge it onto a
fresh branch from master) rather than re-deriving the change from scratch — the
work is sound, only the details below are wrong.

1. <file:line> — <the finding, in its own words, with the empirical cases>
...

Acceptance: <the repo's own test + typecheck commands> green, and the new cases
covered. If any finding turns out not to hold on re-reading, say so in your
verdict and stop rather than forcing a change.
BRIEF
```

- **`run --tier implement` needs no Slack click.** Warden's own lifecycle opens
  the episode when the verdict is `implement` at high confidence and the repo's
  policy allows it; the signed-approval door belongs to `dispatch`, not `run`.
  Never tell the owner a click is pending on a `run` item.
- **Never `abort` the blocked item.** `abort` cancels an *in-flight* episode and
  refuses `merge_blocked`; the old item stays blocked until the new PR validates.
- **Check for an existing fix item first.** Intake is label-free and cards are
  re-posted, so the same issue can already have an item in `verdict`/`implementing`
  — a second `run` for it gets aborted as a duplicate and burns budget. Grep
  `/board` for the repo before opening one.

## Pitfalls

- **`merge` refuses outright on a repo with no `autoMergePaths` entry** in
  `~/SourceRoot/warden/config/triage-policy.json` (`no autoMergePaths declared for
  '<repo>' — path scope is the primary merge gate now`, exit 4). Every PR on such
  a repo is owner-merge-only however clean the validation, and the item sits in
  `merge_blocked` for its whole 7-day window. Check the entry *before* promising a
  merge, and surface it as one decision: add the scope, or merge by hand.
- **Verify a review's blocking finding before relaying it as fact.** The step-7
  review is an LLM pass. A claim of the shape "this pattern also matches ordinary
  cases" is checkable in one command: pull the literal out of the branch
  (`git show <sha>:<file>`) and run the claimed cases through the repo's own
  runtime. Reproducing it also surfaces cases the review missed (false negatives
  beside the false positives), which is what makes the follow-up brief complete
  rather than a restatement.
- **An implement episode outlives the in-turn wait.** `--wait` caps at 170s; an
  `implement` episode runs 10–40 minutes. Reply with what was opened and let the
  5-minute sweeper deliver the verdict into the origin thread. If you must watch
  it, poll `GET /api/jobs/<jobId>` from a **background** script that appends to a
  log file and read the log back — a foreground polling loop is killed by the
  caller's own timeout while the job keeps running, which reads as a failure that
  never happened.
- **A `deferred: repo '<r>' already has an implement episode in flight` note is
  the per-repo lock working, not a stuck item.** The next tick picks it up once
  the sibling finishes; `operations` stays empty. Do not re-dispatch and do not
  call it a retry loop.
- **A blocked item is not evidence the fix is missing.** The repo's `git log`
  since `item.updated_at` and the live state of whatever the verdict named decide
  that; a card can be hours stale because it is only re-synced on a state change.
