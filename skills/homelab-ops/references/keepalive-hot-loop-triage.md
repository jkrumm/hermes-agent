# KeepAlive hot-loop triage

_Use when a supervised service loops while it is up._

A supervised job climbing its run counter with a non-zero exit **while the service
itself answers** is its own shape — not a crash, not a drain the supervisor killed.
The service is healthy and the supervisor is spinning, so everything that asks the
*service* (its own status command, a socket probe, a liveness monitor) reports "up"
throughout, and only the job's own state tells you anything is wrong.

Use this when a restart alert fires on a job whose service is up, when `runs`
climbs at roughly the throttle cadence, or when a component check says "service up"
in the same message that reports a restart FAIL.

## Procedure

1. **Read the job's own state, twice, thirty seconds apart.**

   ```bash
   launchctl print gui/$(id -u)/<label> | grep -E "state =|runs =|last exit|program =|path =|stdout path"
   ```

   Two samples give the rate: launchd throttles respawns to ~10 s, so ~6/min is a
   loop, not a storm of distinct faults. `last exit code = 1` with `state = spawn
   scheduled` at a steady cadence is the signature.
2. **Read the job's stdout/stderr — it holds the one line that explains it.** Take
   the path from `stdout path` in step 1, not from a conventional location: a
   Homebrew service logs to `$(brew --prefix)/var/log/<name>.log`, and
   `~/Library/Logs/Homebrew/<name>/` may simply not exist — an empty directory there
   is not "no logs". A single sentence repeated hundreds of times (`<name> server is
   already running`, "address in use", "lock held") is the whole story.
3. **Establish that the real process is alive and reparented.**

   ```bash
   ps -o pid,ppid,pgid,sid,stat,etime,command -p <pid>
   ```

   ppid 1 plus `Ss` (its own session leader) and **no wrapper process in `ps`** means
   the service detached from the job deliberately. That is the mechanism: the
   wrapper's `waitpid` returns the instant the daemon detaches, the wrapper exits,
   and an **unconditional** `KeepAlive` respawns it — after which every attempt can
   only find the resource held and exit non-zero.
4. **Distinguish it from the two other restart shapes.** No dirty state and no
   cleanup is involved here (contrast the drain-vs-kill asymmetry), and the PIDs in
   the refusals differ because each is a fresh process, not one stuck old one. Say
   which shape it is before proposing anything.
5. **Contain without killing the service — and say what that costs.**

   ```bash
   launchctl bootout gui/$(id -u)/<label>
   ```

   A self-daemonised server in its own session survives `bootout`, with every pane
   and child, because it was never the job's process; the loop stops. The service's
   own destructive verbs (`<service> restart`, a documented "restart the daemon"
   make target) do kill the daemon and everything under it — never reach for them to
   quiet a *supervisor* bug, and never run them when live sessions are in the
   service. State the follow-on: the job is now unloaded, so a boot-path check
   reports `plist missing/unloaded: <label>(not loaded)`, and the return path is
   bootout + bootstrap of the corrected plist (never `kickstart -k`, which does not
   re-read it).

## Why exit 0 is not the fix

Making the wrapper return success changes nothing: an unconditional `KeepAlive`
respawns on *every* exit. The fix is one of two shapes — the wrapper **supervises**
(the parent stays alive as long as the daemon answers and exits only when it
genuinely stops), or the plist becomes conditional so a successful start is not
restarted. Converge the plist through the owning make target, and keep the
vendor-regenerates-the-plist trap in mind: a package manager rewrite of the service
file silently reverts the supervision, so the assertion belongs in the upgrade path
too.

## Pitfalls

- **A liveness check is not evidence about the supervisor.** Whatever asks the
  service will keep answering "up" for the whole loop; the two statements are both
  true and only one is the fault. Quote the job's `runs`/exit, never the service's
  status, as the finding.
- **A self-daemonising command is behaving as designed.** Fix the wrapper whose
  contract assumed a foreground child (fork + `setsid` + wait), not the upstream
  daemon — and check the repo for the knowledge already sitting in a comment: a
  restart-path note that "it is a detached daemon since version N" is proof the
  boot-path wrapper was never migrated.
- **Do not treat the loop as harmless because CPU is low.** The cost is the
  supervisor's own state, unbounded log growth, and a component check that can no
  longer distinguish this job from a crash — contain it and fix the wrapper.
- **Cite the containment verb and the pane cost in the report.** Both destructive and
  non-destructive ways of "restarting" a user-facing service look alike to the next
  reader; name which one you used and which sessions survived it.
