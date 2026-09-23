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
| `merge_blocked`, `implement episode <job> finished 'failed' with no pull request: git remote get-url origin failed (2)` | the repo has **no `origin` remote**, so no worktree `implement` episode can ever push or open a PR | re-running changes nothing — land the change by hand, or dispatch an `in-place` episode (below) |
| `needs_human`, `investigation concluded implement, but repo '<r>' is capped at tier '<t>'` | a policy ceiling, not a bug | the fix is a code change no dispatch can make — hand it to the owner |
| `needs_human`, `implement <job>: <summary>` with `nextAction: human` | the episode itself asked | relay the ask, do not re-dispatch |
| `needs_human`, `schemaVersion N, warden expects M` | pin-vs-server drift | check `make check-schemas`; the episode's work often already landed |
| `needs_human`, `step-7 validation (needs-human): Review ran N reviewers but synthesis failed to serialize a structured verdict` | the review pipeline broke, not the PR — see below | verify the branch yourself, close the item, file the pipeline defect |

**A validation `review` job can break on the very defect the PR fixes.** The step-7
validator is itself a `review` job, so a PR touching `review.ts`'s salvage branch or
`classifyExitFailure` gets validated by the still-broken code path — `needs_human` with
`blocking: []` and a `discussions[0].message` that is only the constructed error string.
That is a self-referential false block, not a finding about the diff: verify the branch
in a throwaway worktree, `close` the item naming it, and `gh pr ready` the PR. Do not
re-dispatch.

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

- **Your brief never reaches the implement episode — the *verdict* does.** The
  lifecycle composes the implement brief from its own template ("re-read that
  investigation's own verdict … then implement the fix it described"), so the
  text you wrote reaches only the investigate stage. An implement episode's
  worktree is cut from **master**, and an unmerged carrier branch's symbols do
  not exist there — so a brief that says "fix on top of PR #N's branch" dies as
  `implement …: no_changes` / `needs_human`: *"investigation targeted unmerged
  commit f15ba7c … the fix needs a human decision on which branch it lands on."*
  Put the **base commit and the checkout mechanism** (`git fetch origin <branch>`,
  `git checkout -b <new> <sha>`) into the brief, require the verdict to name them,
  and state that a master-based re-derivation is rejected. Deciding which branch
  is the landing site is the owner question; `close <event-id> --why` discharges
  the `needs_human` bounce it leaves behind.
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
- **A review finding that says "make this check stricter" is usually not a
  threshold. Measure before briefing it that way.** For a guard that validates a
  model-authored *replacement* of a document (a reviewer/critic rewriting a
  report), no body-level text heuristic can separate a legitimate edit from a
  hallucinated insertion of the same size: measured length ratio, changed
  fraction and 8/20/40-word n-gram overlap are identical (0.99 vs 1.01, 0.15 vs
  0.16, 0.65/0.48/0.40 for both). The fix that works is to change the *contract* —
  the model returns find/replace spans and code applies them by exact match, so
  unchanged content is the original bytes rather than a reproduction, and a span
  that is absent, ambiguous or a no-op is refusable mechanically. Verify the
  candidate design against the classes in a scratch `bun run` before writing the
  brief, and put the measurement in the brief: it is what stops the episode from
  shipping a tighter version of the same predicate.
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
- **Check `/board` for a live sibling before opening the fix item, and again after
  aborting one.** Several sessions read the same card, so this step runs in parallel
  and the dedup can collapse to *zero* carriers — two items aborted each other inside
  two minutes and three replacements landed in the next forty seconds. Survivor is
  the **oldest live item**; abort only the later claim, re-read after your own abort,
  and close the `needs_human` bounce an abort leaves behind. The procedure is
  `concurrent-card-dedup` — do not re-derive it here.
- **A blocked item is not evidence the fix is missing.** The repo's `git log`
  since `item.updated_at` and the live state of whatever the verdict named decide
  that; a card can be hours stale because it is only re-synced on a state change.
- **A remedy is not verified until you run the variant the brief prescribes.** The
  review's own suggested remedy can itself be insufficient, and briefing it as-is
  buys another review round. Concrete case: a citation guard over report prose that
  compares URL sets — "compare exact occurrences/positions instead" closes the
  drop-one-of-two and the swap, but **not** a single URL whose prose context is
  moved (`Alpha is limited [https://a]. Beta is unlimited.` → `Alpha is unlimited.
  Beta is limited [https://a].`): the URL sequence is byte-identical and the
  attribution is inverted. Everything URL-level (set, count, ordered sequence) is
  blind to it, because the pairing lives in the prose. Make the rule categorical —
  no span's `find` or `replace` may contain a citation reference, so every URL in
  the result is an untouched original byte — keep the URL-sequence equality as an
  unreachable-but-asserted invariant, and write the accepted residual (pairing
  inside a reworded span) into the doc comment. Measure the candidate rule against
  the classes with the repo's own runtime before it reaches a brief.
