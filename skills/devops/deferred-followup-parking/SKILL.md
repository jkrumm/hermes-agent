---
name: deferred-followup-parking
description: "Use when a follow-up must wait days for a prerequisite."
version: 1.0.0
metadata:
  hermes:
    tags: [deferred, parking, cron, monitor, followup, prerequisite, merge-gate, findings, cronjob]
    related_skills: [background-work-watch, warden-owner-decision-card, warden-blocked-items, concurrent-card-dedup, claude-dispatch]
---

# Deferred follow-up work

Some work must not start now and must not be lost: the improvements a review listed
beside a change that is still unmerged, the second round a guard needs once the first
lands, a check that only means anything after a deploy. The window is hours, not
weeks — the card carrying the findings has a `state_deadline` and auto-dismisses, a
review payload is queryable at the executor only while the job is recent, and the next
session sees only what was actually written down.

Three moves, in order: **capture** the findings while they exist, **park** the work
behind the gate that must open first, **arm** it on that state change.

`background-work-watch` owns waits measured in minutes; this skill owns waits measured
in days. `warden-owner-decision-card` owns the decision the card is actually asking for
— answer that first; parking is what you do with the findings that ride beside it.

## 1. Capture before it evaporates

- **The executor's job store is short-lived.** sideclaw keeps roughly the last dozen
  submissions, so a completed `review`/`investigate` job answers
  `{"ok":false,"error":"job not found"}` within hours — byte-identical to a job that
  never ran. Anything the projection did not keep is gone; read it while the job is
  live or accept the loss.
- **The ledger keeps the fold, not the payload.** `GET
  http://127.0.0.1:7735/items/<event_id>` exposes `dispatches[].verdict` with
  `summary` / `nextAction` / `confidence` / `recommendation` only. A review's
  `blocking[]` / `discussions[]` / `improvements[]` / `testGaps[]` never reach it, so
  a findings list that arrived only as a card note is typically unrecoverable later.
- **Write down what you have, name what you do not.** Quote the findings you can still
  read into the parked job's prompt; when only part of the list survives, say that in
  the reply and let the armed episode re-derive the rest from the merged diff rather
  than inventing items.

## 2. Park behind the gate, not beside it

- **Do not arm the work now.** While the change that owns the same files is unmerged, a
  second episode edits the same hunks and buys a conflict; the parked follow-up waits
  for the merge, which is also what makes the owner's merge the implicit go-ahead.
- **Never park against the owner's decision.** If the card asks a question too, that
  goes back answered, not parked — measure it (`credential-scope-verification` for a
  credential, `runtime-claim-verification` for a behaviour claim) and recommend. Only
  the non-blocking tail is parked.
- **Check for an existing carrier first.** `curl -s http://127.0.0.1:7735/board` — a
  sibling item in `investigating`/`implementing`/`validating` for that repo already
  carries the ask (the lock is per repo), and a duplicate parks nothing and burns an
  episode (`concurrent-card-dedup`).

## 3. Arm on the state change — a monitor-gated cron

A monitor's output is hashed each tick: an unchanged value suppresses the run entirely
(no LLM, no delivery), and the change wakes the agent once.

```bash
# 1. deterministic state script — no timestamps, no ordering noise,
#    ~/.hermes/scripts/<thing>-state.sh  (that dir is a symlink into the
#    hermes-agent repo, so commit the file there)
gh pr view <n> --repo <owner>/<repo> --json state -q .state || echo UNKNOWN

# 2. park the follow-up behind it
#    cronjob_manage(action='create', name=…, schedule='every 3h', deliver='origin',
#                   monitor='<thing>-state.sh', skills=['claude-dispatch', 'warden'],
#                   prompt=<self-contained, branching on the state>)
```

- **The prompt must be self-contained and branch on the state.** The first tick always
  runs as baseline: make the not-yet branch exactly one line ("<thing> noch offen —
  Followup bleibt geparkt.") and the ready branch the entire task, including the literal
  `run <repo> --tier implement` invocation, its `--why` and its brief.
- **Gate the armed branch on the repo lock** — `/board` again, inside the armed branch —
  so a parked job cannot fire into an in-flight episode on the same repo.
- **Deliver to origin and name the job id in the reply.** A parked job is otherwise
  invisible in the thread, and the card that motivated it is gone by then.
- **The job goes inert, not away.** Once the state settles, every tick hashes identical
  and no run happens; leaving it in the job list is correct. Do not remove it while the
  follow-up is still open.

## Pitfalls

- **A prerequisite already satisfied is not a parked job.** If the gate is already open,
  dispatch now — parking work that can start reads as progress and produces nothing.
- **Do not park what a Warden item already owns.** An open item rides its own lifecycle;
  a cron that re-fires it duplicates the loop.
- **A parked job is not a watcher and a watcher is not a parked job.** Minutes → background
  process with `notify=True`; days → monitor-gated cron. A foreground polling loop dies
  long before either.
- **A generated script under `~/.hermes/scripts/` is repo content** — commit it in
  `hermes-agent` in the same session, or the parked job's monitor becomes an untracked
  local file nobody can reconstruct.
- **Say the deadline.** When the motive is an expiring card, one clause on when it dies
  (`state_deadline`) is what tells the owner why this exists at all.
