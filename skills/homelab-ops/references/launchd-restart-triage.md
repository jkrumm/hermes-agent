# LaunchAgent restart triage (Mac Mini)

`devhost-health` flags **every** LaunchAgent restart as FAIL, by design — it
cannot tell a graceful reload from a crash, so it reports both and leaves the
verdict to you. Most restarts on this machine are the dev loop: someone edits a
repo, runs its `reload` target, launchd kickstarts the agent, the runs counter
climbs. That is expected noise, not an incident.

The named alert shapes themselves — the hermes gateway restart, the dev-reload
burst, the session-teardown case where an agent *vanishes* rather
than restarts — live in `alert-patterns.md`. This file is the mechanics behind
those verdicts: how to read the signal, what actually settles the question, and
what a restart costs even when it is benign.

## Read the exit, not the signal name

`Terminated: 15` is SIGTERM, which is what `launchctl kickstart -k` sends. It is
the *graceful* path and it is what a reload looks like. A restart is only
suspicious for its exit code and its cadence:

| Evidence | Verdict |
|-|-|
| SIGTERM + exit code 0 + one restart | Clean reload. Nothing to do |
| SIGTERM + exit 0, count climbing over minutes, correlated with repo activity | Dev loop. Nothing to do |
| Non-zero exit, or a signal other than 15 | Real fault. Escalate |
| Restarts seconds apart with no repo activity | Crash loop. Escalate — do not "restart it again" |
| Agent gone from the user domain rather than restarting | Session teardown, a different failure — `launchd-repair <label>` |

## The decisive test is correlation, not launchd

Whether the process is alive right now says nothing: KeepAlive means it is
almost always alive. What separates a reload from a crash is whether a human was
working on that repo at those timestamps.

- **Reachable from here** — local read-only correlation: the service's checkout
  (`git log` with times, working-tree mtimes), whether a Claude Code session is
  running, and `~/Library/Logs/devhost-health.log` for the restart cadence. None
  of these are infrastructure mutations.
- **The verb for "has it settled"** is `devhost-health --why "…" --confirm`: it
  takes a fresh heartbeat and reports the current restart history, which is what
  closes the alert. It reports; it does not repair.
- **`launchctl print` and `log show` are raw launchctl.** They belong in the
  command you *recommend* when escalating, not in your own hands — the operating
  rule holds here exactly as it does for `ssh` and `docker`.

## A benign restart still strands work

Verify this before closing a triage, and say so in the summary even when the
verdict is "no incident":

- **A reload kills whatever the agent had in flight.** A service that runs jobs
  (a worker, a queue consumer) loses the running ones on SIGTERM, and the caller
  waiting on them is not told. Name what was running in the summary.
- Reading that state is a raw log/database read with no verb behind it, so recommend
  the query rather than composing one.

## Two things that mislead people

- **`launchctl kickstart -k` does not re-read the plist.** It restarts from
  launchd's cached job definition. Only `bootout` + `bootstrap` reloads the file.
  A plist edit that "was applied" and demonstrably is not behaving is almost
  always this, not a bad edit.
- **A restart is not a repair.** Restarting a service that is crash-looping
  resets the counter, destroys the log window that would have explained it, and
  changes nothing. Escalate with the repeating error instead.

## Closing the triage

Dev loop: say "no incident — active development on `<repo>`, N restarts, all
SIGTERM/exit 0", name any interrupted jobs, and stop. Real fault: escalate in the
standard shape — what you observed, the failure class, the exact command you
recommend, and what you ruled out.
