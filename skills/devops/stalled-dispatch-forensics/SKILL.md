---
name: stalled-dispatch-forensics
description: Use when a dispatch or item looks stuck or queued.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, sideclaw, dispatch, queue, stuck, triage, forensics, logs]
    related_skills: [warden, warden-digest-triage, claude-dispatch]
---

# Stalled dispatch forensics

`queued`, `deferred`, `pending`, `needs_human` are claims about a moment, not a
state. Three surfaces each hold a third of the answer — the ledger (Warden), the
executor's job queue (sideclaw), and the consumer's own logs — and a card, a note
or a single log line is never enough to call something stuck. Read all three
before reporting either "pacing" or "wedge".

Reading Warden's own status is the `warden` skill; the daily digest is
`warden-digest-triage`. This skill is the cross-surface question: *is this item
actually progressing, and if not, whose defect is it?*

## Procedure

1. **Read the live item, never the card.** The card and its `note` are a
   snapshot from the last state change; the ledger is current.

   ```bash
   curl -s http://127.0.0.1:7735/items/<event_id>   # item + dispatches + operations + transitions
   ```

   Or read the ledger directly, read-only, through **warden's own venv python**
   (macOS `/usr/bin/sqlite3` has no `-uri` and dies `unable to open database file
   (14)` on `file:…?mode=ro`, which reads like a missing ledger):

   ```bash
   cd ~/SourceRoot/warden && .venv/bin/python3 -c "
   import sqlite3
   c = sqlite3.connect('file:/Users/jkrumm/.warden/warden.db?mode=ro', uri=True)
   c.row_factory = sqlite3.Row
   for r in c.execute(\"SELECT event_id,state,repo,dispatch_job,note FROM triage_items WHERE state NOT IN ('fixed','quiet','closed','dismissed','note','ignored') ORDER BY event_id\"):
       print(dict(r))
   "
   ```

   Schema traps: the history table is `item_transitions` (not `transitions`),
   `operations` is keyed by `op_id` (no `id` column), and `triage_items` has no
   `source` column — the source lives on `events`.

2. **Take the job id the item names to the executor's queue.** A Warden item's
   `dispatch_job` / `implement_job` / `validation_job` is a sideclaw job:

   ```bash
   curl -s http://127.0.0.1:7705/api/jobs/health      # {ok, running, pending, max, oldestPendingAgeMs, failedLastHour, draining}
   curl -s http://127.0.0.1:7705/api/jobs/<job-id>    # status, startedAt, progress.turns/lastAction/idleMs
   curl -s http://127.0.0.1:7705/api/dispatch-policy  # the boundary's own per-repo ceilings
   ```

   `pending` with `startedAt: null` means never started, not hung. The cause is
   almost always the global concurrency cap: `running == max` (default 3) makes
   every other submission legitimately wait, and `health.ok: false` with
   `oldestPendingAgeMs` past ~15 min and `draining: false` is a real backlog.
   `idleMs` large *and growing* is the only wedged-session signal; a small
   `idleMs` with a moving `lastAction` is a working episode, however long it runs
   (workers have no turn limit and no wall-clock ceiling — the no-stdout idle
   watchdog is the only kill rule).

3. **Classify, then report the mechanism.** Pacing (a cap doing its job) needs no
   action and no alarm; a wedge needs the refusal text from `receipt_json` or the
   job's `error`. Lead with which of the two it is.

4. **A defect outside the repo you are reading gets filed, with the measurement.**
   Reproduce it once with a command whose output you can quote, then write the
   issue. Do not file from a log line alone.

## Pitfalls

- **A `note` is a snapshot and can name a reason that is no longer true.** The
  `queued: at MAX_OPEN_INVESTIGATIONS=N` note is written while the row is still
  `new` and is **not cleared** when the claim to `investigating` succeeds, so a row
  with a live `dispatch_job` can still carry "waiting for a free slot" — on the
  board, in Argo, and in any summary you write from it. Check `dispatch_job IS NOT
  NULL` before repeating a `queued:`/`deferred:` note as current fact.
- **A log line that repeats on a fixed interval is a defect, not noise.** Size it
  and date it before dismissing it — a warn line every ~60s for hours is a
  permanently broken code path that nobody read:

  ```bash
  grep -c "<event-name>" ~/Library/Logs/<service>.jsonl
  grep -n "<event-name>" ~/Library/Logs/<service>.jsonl | head -1   # first occurrence
  grep -n "<event-name>" ~/Library/Logs/<service>.jsonl | tail -1   # last
  ```

  When one event name carries **different error text over time**, the earliest
  occurrence of the newest shape dates the regression — that bracket is the whole
  finding, and it is cheap.
- **Endpoint drift: a consumer that hardcodes a service's loopback port degrades
  silently when the service moves.** The consumer's failure mode is a swallowed
  `{ok: false}` plus a warn line, so the surface just renders empty. Check all
  three, in order: who actually listens (`lsof -nP -iTCP:<port> -sTCP:LISTEN`),
  what the consumer defaults to, and whether an env override is even set (grep the
  consumer's `.env` and its LaunchAgent plist — an unset override means the
  hardcoded default is live). Prefer fixing the default over setting the override:
  the override masks the drift for one caller and leaves the next one broken.
- **A policy claim lives in three places and they drift.** Prose (a DESIGN/CLAUDE
  paragraph), a local config file, and the enforcing boundary's own endpoint. The
  config is what runs; the boundary is what actually refuses; the prose is the
  thing that goes stale. When a ceiling is in question, read the config *and* the
  boundary's live endpoint, and treat prose that contradicts them as its own
  finding rather than as the answer.
- **`gh issue create --body "$(cat <<'EOF' … )"` mangles the body.** Inside `$( )`
  with a quoted heredoc, backticks and `$` in the body still get shell-expanded,
  producing `No such file or directory` for every code span and a body with holes
  in it — and the command still exits 0 with a URL. Write the body to a file
  (`write_file`) and pass `--body-file`, then read it back with
  `gh issue view <n> --json body` to confirm what actually landed.

## Report shape

Verdict first: **pacing, not a wedge** (name the cap and the number) or **wedge**
(name the refusal). Then one line per finding: what it is, the mechanism, what you
filed or changed. Do not enumerate everything you checked and found healthy — say
"rest green".
