---
name: prerequisite-gated-cron
description: Use when work must fire when an absent resource returns.
version: 1.0.0
metadata:
  hermes:
    tags: [cron, watchdog, no-agent, parking, prerequisite, quiet-by-design]
    related_skills: [deferred-followup-parking, background-work-watch, human-queue]
---

# Prerequisite-gated cron — arm it, don't poll it

Use when a task is blocked on something *absent right now* — a machine that is
asleep, a host that must come back, an artifact that must appear — and has to fire
exactly once when it returns, without an LLM run per tick and without nagging the
channel. The wait is hours to days, so a foreground loop is wrong and a plain
recurring agent job costs a model call every tick.

The two variants are not interchangeable: a **`no_agent` watchdog** runs a fixed
action and prints fixed text (no inference at all); a **monitor-gated agent job**
(`monitor:` + `skills:`) hashes a state script and wakes the agent only when it
changes, for work that needs reasoning. Choose the watchdog whenever the action and
the wording are already known.

## Procedure

1. **Write the worker under `~/.hermes/scripts/`** (symlinked into the hermes-agent
   repo — commit it there in the same pass as the registry row). One script owns the
   prerequisite probe, the action, the backoff and the report.
2. **Gate on the real prerequisite, never a proxy.** If the action is an ssh hop, the
   gate is that hop: `ssh -q -o BatchMode=yes -o ConnectTimeout=8 <host> true`. Tailnet
   presence says nothing about the daemon behind the door, and a probe that answers
   while the door is shut fires the job into a void.
3. **Detach anything that can block.** A native dialog or an approval that waits for a
   human holds the tick (a GUI give-up alone defaults to 600s). Launch it with
   `nohup timeout 900 … >/dev/null 2>&1 &` and `exit 0`; the action writes its own
   result, so the *next* tick reports it.
4. **Two markers, never one.** An mtime age check gives at most one attempt per N hours
   (`stat -f %m` on macOS, `stat -c %Y` on GNU); a separate `.reported` marker makes the
   resolution message fire exactly once, after which every tick is silent forever. Keep
   both outside the namespace of the thing they track.
5. **Honour the action's own idempotency guard.** When the tool refuses because a result
   already exists, that refusal *is* the guard — check the artifact first and never work
   around it.
6. **Report the outcome and verify it at the consumer.** One line: what resolved, the
   status/exit, plus a live probe of the thing the action was supposed to unblock (the
   port, the endpoint, the file). A status file is a claim; the probe is evidence, and a
   "still blocked" after a successful action is a finding to report, not to hide.
7. **Register the job or `make status` goes red.** Every live job needs a row in
   `hermes-agent/docs/scheduled-jobs.md`; `scripts/check-cron-registry.py` (invoked by
   `make status`) asserts both directions — a row with no live job, and a live job with
   no row. A job that is disabled *without* a recorded `paused_reason` matches neither
   state: remove the spent job and name it under `## Retired`.
8. **Test every branch against a temp state dir**, `XDG_STATE_HOME=$(mktemp -d)` plus a
   fake `ssh` on `PATH` that exits 0 — a test run that consumes the real backoff marker
   or fires the real dialog poisons the job it was testing.
9. **If the gate is already open, do the work now.** Arming a job whose prerequisite is
   already satisfied looks like progress and produces nothing.

## Pitfalls

- **A `no_agent` script that exits non-zero alerts on every tick, and a timeout does the
  same.** Every path ends in `exit 0`; use `set -u` without `set -e`, and guard
  individual commands with `|| exit 0` / `|| true`.
- **Empty stdout is the whole trick.** A `no_agent` job delivers stdout verbatim and
  sends *nothing* when it is empty — that is what makes "silent until there is news"
  free. Printing a "still waiting" line every tick recreates the noise the design exists
  to remove.
- **Monitor output must be byte-stable for an unchanged state.** Timestamps, durations,
  ordering, or a peer's `last seen 4m ago` make every tick look changed and wake the
  agent (or re-fire the watchdog) forever. Print one token, computed from the state
  alone.
- **A parked job is not a watcher.** Minutes → a background process with notification;
  hours to days → a cron. A foreground polling loop dies with the session.
- **Never hand-edit `cron/jobs.json`.** It is gitignored runtime state carrying its own
  copy of the prompt; create/edit through `cronjob_manage` (or `hermes cron`), and edit
  the registry doc separately.
