# Live-process change verification

_Use when a fix may not be live in a running process._

A file on disk is not a running process. This is the class of task "I changed the
source or the config — is the thing that is actually serving requests using it?"
It is the step that must come BEFORE reporting a fix as landed, and it is distinct
from deploying (that is `homelab-ops` / `vps-app-verification`).

## The mechanism

A long-lived Python process imports a module **once**. Editing the file changes
nothing for that process: there is no reload path and no mtime watch.
`importlib.reload` only happens where code calls it explicitly (a few CLI
maintenance paths), never for a tool module.

- **A patch is inert until the owning process restarts.** For Hermes that process
  is the gateway; for a service it is the container.
- **The restart is a human action and is guard-blocked from inside the process it
  would kill.** Hand over the exact command; do not look for a way around the guard.
- **A restart only helps when the process is genuinely stale.** If the log slice
  since process start is already clean and already shows the new behaviour, the
  answer is "nothing to do", not "please restart".

## Procedure — prove it, do not infer it

1. **Record the process boundary.** `ps -o lstart= -p <pid>` (or `lstart,etime`),
   and compare it against the mtime of the file you changed. Source newer than
   process start is the *hypothesis*, not the proof: a process can also be stale
   because it imported the module before the change, within its own lifetime.
2. **Make the new code's effect observable, then look for it in the process's own
   output.** Strongest signal: the patched code emits a string the old code could
   never produce — a new log marker, a rewritten file, a new symbol. Grep the
   process's log for that marker.
3. **Run the same code path in a fresh interpreter and diff the two outputs.**
   This is the decisive test and it needs no restart:

   ```bash
   cd ~/.hermes/hermes-agent && ./venv/bin/python3 -c "
   import sys, logging; sys.path.insert(0,'.')
   logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
   from tools.<module> import <EntryPoint>
   print(<EntryPoint>(...).<call>(...))"
   ```

   If the fresh interpreter prints the new marker and the process's log line for
   the same path does not, the process is stale — a two-sided proof, not a guess.
4. **Third, cheap, independent signal:** compare the `.pyc` header's recorded source
   mtime against the source's actual mtime. A valid `.pyc` only proves the file is
   importable; the *process* may have imported it earlier. Use it to rule out a
   compile problem, never to prove liveness.
5. **Report, then hand over the one command.** Name the PID and its start time, the
   fix's commit or mtime, and the marker that is missing — then the restart.

## Pitfalls

- **Do not report a fix as landed because the file changed.** The failure mode is
  reporting "fixed" while the old behaviour keeps firing one new log line per
  event, so the report and the evidence contradict each other.
- **Log lines newer than the fix's mtime but older than the process restart belong
  to the OLD code.** Slice every log read at the process start (`hermes-gateway`
  Rule 0) and count only what is newer than the restart; otherwise you attribute a
  dead incarnation's noise to the fix, or the fix's absence to the wrong cause.
- **`make patch-check` green proves the patch is APPLIED, not LIVE.** It compares
  files on disk. It is a precondition for step 2, never a substitute for it.
- **When the only exit from a stuck state is a clock, read the deadline before
  scheduling anything to act on it.** A cleanup scheduled to run before the
  deadline fires is a silent no-op, and the state may resolve itself first.
