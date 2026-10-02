---
name: background-work-watch
description: "Use when waiting on work that takes minutes (jobs, builds)."
version: 1.0.0
metadata:
  hermes:
    tags: [background, wait, watch, polling, notify, jobs, timeout]
    related_skills: [warden-item-watch, dispatch-liveness-verification, heartbeat-monitoring, agents]
---

# Waiting on multi-minute work

Anything that takes minutes — a dispatched episode, a build, a deploy, a
migration, a supervised job — is watched, not awaited. Hold the reply open for it
and the call gets cut mid-wait with its history gone; answer the disposition you
have *now* and nothing is lost, because the watcher carries the outcome back on its
own.

For a **Warden item**, `devops:warden-item-watch` owns the lifecycle (states,
off-ramps, what each one wants) and `dispatch-liveness-verification` owns the
executor check. This skill is the transport: how the wait is run here.

## Procedure

1. **Name the exit set before starting.** Which states mean *done* (including
   refusal/blocked states) and which mean *needs a human*. A watcher without an
   exit set runs to its timeout and reports nothing useful.
2. **Write the watcher to a file** (`write_file` → `/tmp/watch-<thing>.sh`), never
   an inline one-liner: one timestamped line per poll, a `case` that `exit 0` on
   the first terminal state, and a final `TERMINAL_STEP=<state>` marker line so the
   log tail is self-explanatory.
3. **Run it as ONE tracked background process**, output redirected:

   ```bash
   # terminal(command="/tmp/watch-thing.sh > /tmp/watch-thing.log 2>&1",
   #          background=True, notify=True)
   ```

   `notify=True` fires exactly once, on exit. No `sleep` chain in the turn itself.
4. **Reply now with the current disposition** plus one clause that a watcher is
   running — current state, never a projection of what will happen.
5. **On the notice, read the log and verify at the source** — the artifact itself
   (PR diff and `state`, deployed file, service response), never the job's own
   `summary`/`result` string. Report once, then stop talking about it.

## Pitfalls

- **A foreground call is cut at its ceiling, and the `terminal` parameter is
  `timeout` (seconds).** A stray `timeout_s` is silently ignored and the call falls
  back to the 180 s default — so `for … sleep …; done` in the foreground dies
  mid-loop with its history gone, and a wait you asked to be ten minutes long is
  not one. Any wait beyond a couple of minutes belongs in a background process.
- **`nohup … &` inside a background call is a trap**: the call returns instantly,
  so the completion notice fires before the loop has done anything. Run the loop
  directly as the background command.
- **A projected state is not a terminal state.** A queue position (`pending`,
  `queued`, waiting on a slot) and a transient state the next tick will consume are
  both mid-flight. Ask the executor — the process or API that actually runs the
  work — before calling anything stuck or done.
- **Exit on refusal states, not just success.** `failed`, `cancelled`, `blocked`,
  `needs_human`, `merge_blocked` end the watch too; a loop that exits only on
  success burns its whole timeout on a job that died in the first minute.
- **A large elapsed time is not a hang.** The stuck signal is a growing idle gap
  between progress updates (`idleMs`, `lastActivityAt`), not raw runtime; the
  response is naming what is ahead in the queue, never killing or restarting a job
  to "unblock" it.
- **Never re-dispatch or re-run because a poll looked slow.** One unit of work, one
  episode; a duplicate burns the same session for the same answer.
- **Cross-check the exit set against the item's transition table.** Exiting on a
  state the pipeline consumes on its next tick reports an unfinished investigation
  as the result of work that never started.

## Command hygiene inside the watcher

- **Read repo files by absolute path; `cd` only to change the repo.** `cd <repo> &&
  <cmd>` injects that repo's `AGENTS.md` / subdirectory context into the tool
  result — up to 32k chars — and it is re-sent with every later call.
- **Write scripts, never inline heredocs** — an inline heredoc body loses its
  quoting and backticks / `$(…)` execute in the outer shell.
- **Parse with `~/.hermes/hermes-agent/venv/bin/python3`**: `curl -s -o /tmp/x.json
  <url>` and then a separate `python3 -c "…json.load(open('/tmp/x.json'))…"` (piping
  curl into the interpreter trips the interpreter-scan guard); for SQLite,
  `sqlite3.connect("file:<path>?mode=ro", uri=True)`, since the macOS CLI has no
  `-uri` and a live ledger is only ever opened read-only. Print a distilled value,
  not a payload dump.
- **Env vars inline, never `export`ed** — the shell session persists across calls;
  `pgrep -f <pat>` needs a bracket-search (`[h]ermes`) or it matches its own shell.
- **Batch independent reads into one call** — several unrelated checks in one turn
  cost one round-trip.

## Report shape

Verdict first, German: what is true right now, what the watcher is waiting for,
nothing else. Then silence until the outcome — no poll-by-poll narration, no
"soll ich …?" for work already in flight.
