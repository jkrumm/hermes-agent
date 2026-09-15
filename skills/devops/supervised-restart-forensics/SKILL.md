---
name: supervised-restart-forensics
description: "Diagnose supervised restarts: kill deadline vs drain"
version: 1.0.0
metadata:
  hermes:
    tags: [launchd, systemd, supervisor, restart, sigterm, sigkill, drain, timeout, forensics, keepalive, throttle]
    related_skills: [homelab-ops, hermes-gateway, warden]
---

# Supervised restart forensics

Use when a service manager restarted a process and the app's own logs tell a story that
does not add up: a burst of "already running / refused to start" errors, a lifecycle
ledger reporting an unclean exit, a service that came back after a gap, or a verdict
that blames a hang.

Applies to anything on this estate with a supervisor: the Hermes gateway, sideclaw,
Warden's five LaunchAgents, audio-gateway, weatherorb — launchd plists with `KeepAlive`, or
systemd units.

**The app's log is the least authoritative source in the room.** The supervisor's own
log, the process table, and a counter-case outrank it. Read them before concluding.

## The two clocks are the whole class of bug

Every supervised restart has two independent deadlines, set in different places by
different people:

| Clock | Owner | How it is set |
|-|-|-|
| Kill deadline (SIGTERM → SIGKILL) | the supervisor | launchd `ExitTimeOut` / systemd `TimeoutStopSec` |
| Drain budget | the app | its own config (e.g. a restart-drain timeout) |

When the kill deadline is **shorter** than the drain budget, the supervisor kills the
process mid-drain. Everything downstream — refusals, unclean-exit records, respawn
storms — follows from that one asymmetry. Check it first, before any other hypothesis.

Watch for the case where one supervisor path *derives* its deadline from the app's
budget and another path hardcodes a constant. The derived path looks fine, so the
constant one goes unnoticed until a long drain exposes it. Verify both live:

```bash
grep -A2 ExitTimeOut ~/Library/LaunchAgents/<label>.plist   # launchd: constant?
grep -n <drain_setting> ~/.hermes/config.yaml               # app: what budget?
```

## Procedure

1. **Bound the log read to the current process.** `pgrep -f "<process pattern>"`,
   `ps -o lstart=,etime= -p <pid>`, then slice the log at that timestamp. Never quote a
   line older than the current process start — these logs span restarts.
2. **Count the symptoms and collect their PIDs.**

   ```bash
   grep -an "<refusal message>" <app log>
   ```

   One PID repeated N times = **one** stuck old process and N respawns. Different PIDs =
   a genuine respawn storm. These are different findings; do not report the first as the
   second.
3. **Read the supervisor's log — the mechanism is not in the app log at all.**

   ```bash
   log show --style compact --start "<T-2m>" --end "<T+3m>" 2>/dev/null \
     | grep -E "<label>" | grep -iE "SIGTERM|SIGKILL|did not exit|spawned|exited due|throttle"
   ```

   The tell: `Service did not exit N seconds after SIGTERM. Sending SIGKILL.` then
   `exited due to SIGKILL`, then a respawn every throttle interval. Filter the noisy
   subsystems out of any broad grep — `cfil_inp_log`, `so_gencnt`, `mDNSResponder`,
   `nw_path_libinfo`, `socketfilterfw` dominate and bury the launchd lines.
4. **Establish which process the supervisor actually killed.** If the plist wraps the
   real process in a helper (a log-timestamping shim, a launcher), SIGTERM lands on the
   **wrapper** and is forwarded. The supervisor kills the wrapper; the child survives,
   is reparented to PID 1, and keeps working **while still holding its lock file**. The
   app records its own parent, so this is directly readable:

   ```bash
   grep -a "Shutdown context" <app log>
   ```

   `parent_pid=<wrapper>` on the first signal and `parent_pid=1` on the second is the
   entire mechanism in two lines. A reparented child still holding the lock is what
   makes every subsequent respawn refuse.
5. **Prove the child was working, not hung.** A drain is *work in progress*; a hang is
   *no progress*. The app's own log goes quiet in both cases once it stops emitting phase
   lines, so look outside it:

   ```bash
   log show --style compact --start "<T>" --end "<T+3m>" 2>/dev/null | grep "<old-pid>" \
     | grep -viE "cfil_inp_log|so_gencnt|mDNSResponder|nw_path"
   ```

   Signs of life from a killed-but-reparented PID: a `socketfilterfw` flow entry for that
   PID (it opened a connection); a `cfprefsd` connection invalidated because that PID
   "cancelled the connection or exited" (the real end of the drain); a request-log line
   served by it after the kill. Compute the duration from the first SIGTERM to that last
   sign of life and compare it to the configured budget. **Inside the budget = a drain
   the supervisor killed early.** Silence for the whole budget is a hang — only then is a
   stack dump the right next step.
6. **Run the counter-case before writing any conclusion.** Repeat the same operation with
   nothing in flight and check the symptom count:

   ```bash
   grep -a "drain done" <app log> | tail -3
   ```

   A sub-second drain with `active_at_start=0` and zero refusals in the same window
   proves the symptoms track in-flight work, not the restart. This is the cheapest
   falsifier of a "stalled" claim and it takes one command.

## Why the refusals appear at all

The app guards against two instances sharing one home by holding a lock file plus a PID
record. A respawned instance reads that record, sees a live process, logs the refusal and
exits non-zero. KeepAlive then pends the next respawn by the throttle interval, so the
refusals arrive at a steady cadence for as long as the orphaned drain runs. The count is
roughly `drain duration / throttle interval`, not a count of distinct failures.

Launchd states worth recognising: `Service did not exit N seconds after SIGTERM.
Sending SIGKILL.` (the deadline hit); `exited due to SIGKILL | sent by launchd` vs.
`exited due to exit(N)` (killed vs. chose to exit — only the first is the deadline);
`Service only ran for N seconds. Pushing respawn out by M seconds.` (the throttle);
`cannot spawn: service is throttled` (a respawn dropped, not one that failed);
`pended nondemand spawn = inefficient` (a respawn queued that may never fire).

## Pitfalls

- **A burst of refusals is one event, not N faults.** Report the single root cause and
  the count, not a list of incidents.
- **An unclean-exit record is a *result*, not a second symptom.** A process killed by
  SIGKILL runs no exit path, so the ledger will say `exited UNCLEANLY` /
  `prior_unclean_exit`. That is the kill you already identified — do not cite it as
  independent evidence of a crash, OOM, or VM death.
- **A drain that outlives the kill is not data loss.** A well-built app replays the
  interrupted work on the next boot (look for an auto-resume line). Check before
  alarming.
- **Silence in the app log after a shutdown notification is ambiguous.** It is equally
  consistent with a long in-budget drain and with a hang. Never call it a hang without
  step 5 and step 6.
- **A high-confidence agent verdict's *mechanism* can be wrong while its *finding* is
  right.** `confidence: high` means the episode is sure of its conclusion, not that its
  causal story survives primary evidence — an episode reads logs and source, not the
  supervisor, the process table, or a counter-case. Verify the causal claim, and when it
  fails, say so plainly rather than softening it into agreement.
- **Check whether the fix is even reachable before offering to dispatch it.** The file
  may live in a checkout that is not the dispatchable repo, or the repo may be capped at
  a read-only tier. Name the ceiling and the real owner of the file instead of
  dispatching into a wall. On this estate the upstream Hermes checkout is
  `~/.hermes/hermes-agent` (origin `NousResearch/hermes-agent`) and owns `hermes_cli/`;
  `~/SourceRoot/hermes-agent` holds config, skills, scripts and patches and has no
  `hermes_cli/`.
- **An upstream issue family is not the same as your issue.** A cluster of open issues
  about one subsystem can all describe adjacent symptoms while missing the variant you
  found. Search, then state which mechanism is already covered and which is the gap —
  do not cite the family as "known" and stop.

## Report shape

Lead with the mechanism in one sentence, then:

- what the supervisor did, with the two timestamps (signal, kill) and the two clocks;
- which process was actually killed, and what survived it;
- the counter-case that rules out the competing explanation;
- current state, verified independently of the app's own log;
- what you did **not** do, and why (no dispatch past a ceiling, no policy write).
