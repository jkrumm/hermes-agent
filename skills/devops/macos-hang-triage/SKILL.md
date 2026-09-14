---
name: macos-hang-triage
description: "Use when a macOS path hangs or a daemon is wedged."
version: 1.0.0
metadata:
  hermes:
    tags: [macos, mini, hang, uninterruptible, launchd, containermanagerd, coreaudio, group-containers, wedge, killall]
    related_skills: [homelab-ops, sudo-handoff, homelab]
---

# macOS hang triage

Use when a command on the mini (or any macOS host) **hangs instead of failing** —
`rm -rf`/`rmdir`/`mv`/`ls` that never returns, or `Interrupted system call`
(Errno 4) from `ls`, `xattr`, `rm`. The disk is almost never the problem; a wedged
launchd service is.

## The rule

A hang is an answer, not a reason to wait. Never run a suspected-hanging operation
bare in a foreground shell — wrap it in a timeout so the hang is *measured* rather
than burning the call budget. Never escalate to a reboot before you have identified
the owning service and tried killing it.

## Procedure

1. **Bound every probe.** `timeout 8 <cmd>` at the shell, or in Python:
   `subprocess.run(cmd, capture_output=True, timeout=8)` and treat
   `TimeoutExpired` as the result. A bare `rm -rf` on a wedged path blocks until the
   terminal tool's own timeout kills it, and you learn nothing.
2. **Find the boundary.** Run the same operation in a *sibling* directory
   (`~/Library/Caches`, `~/Library/Application Support`) and in the failing parent.
   Sibling fine + parent hanging = a service wedging that parent, not a bad disk.
   `stat` on the path usually still succeeds while `listdir`/`ls` hangs — that
   asymmetry is the fingerprint of a stuck container/namespace manager.
3. **Rule out a stale mount.** `mount | grep <path>` and `df -h <path>` — an
   `autofs`/`map auto_home` entry or a path resolving to a different volume changes
   the diagnosis entirely.
4. **Name the owning service.** `ps -Ao pid,stat,etime,comm | awk '$2 ~ /^[UD]/'`
   lists uninterruptible processes; `pgrep -af <daemon>` plus
   `ps -o pid,user,etime,comm -p <pid>` shows who owns it. **The user column is the
   finding** — a per-user manager running as a service account (`_coreaudiod`,
   `_windowserver`) is what makes a blanket `killall` on that account destructive.
5. **Kill it, as root if you must.** These are launchd Mach services, so try the
   domain form first (`launchctl kill SIGKILL user/<uid>/<label>`), then the pid
   (`kill -9 <pid>`). launchd respawns them; a respawned-and-working service is the
   goal, not a failure. Killing a service owned by another user needs sudo — hand
   that to the human (`sudo-handoff`), do not route around it.
6. **Prove the repair, don't assume it.** Re-run the step-2 control: a `mkdir` +
   `rmdir` of a fresh directory in the previously-hanging parent must both succeed.
   Then finish the original work.
7. **If it is still wedged, say so and stop.** A reboot is the remaining fix; name
   it as the recommendation rather than looping on kills.

## Known wedge: `~/Library/Group Containers`

- **Symptom:** `ls`/`xattr` return `Interrupted system call`; `rm -rf`, `rmdir`,
  `mv` hang; a `mkdir` of a *new* dir in the same parent hangs too.
- **Cause:** `containermanagerd` (per-user, launchd Mach service) is stuck. It runs
  as **`_coreaudiod`**.
- **Trigger:** a blanket `killall coreaudiod` — typically to refresh the Core Audio
  HAL driver list after removing a `*.driver` under `/Library/Audio/Plug-Ins/HAL`.
  The kill takes the container manager down with it and it returns wedged.
- **Blast radius:** every create/delete under `~/Library/Group Containers` — so any
  app that mints a container, not just the paths you were deleting. Existing data is
  intact; the entries are ordinary empty directories.
- **Fix (root):** `launchctl kill SIGKILL user/<uid>/com.apple.containermanagerd`,
  else `pgrep -f containermanagerd | xargs -r kill -9`. Do **not** kill
  `com.apple.containermanagerd.system` — that is the root/system instance and not
  the wedge.

## Pitfalls

- **Never `killall <daemon>` without checking its user.** `killall coreaudiod`
  kills everything running as `_coreaudiod`, which includes `containermanagerd`. The
  stale HAL device entry you were trying to clear is cosmetic and clears on reboot;
  restart coreaudiod through launchd (`launchctl print system | grep -i coreaudio`
  names the label) if it must be refreshed, and run
  `pgrep -f containermanagerd` afterwards.
- **A wedged parent is not the entry's fault.** Retrying the delete, with `sudo`, or
  with `find -delete`, all hang identically — the manager is the fault. Stop
  retrying variants and go to step 4.
- **Do not leave test artifacts behind.** Control `mkdir`s under `Group Containers`
  are themselves blocked by the wedge and survive as dot-dirs (they surface as a
  `?1` in a shell prompt); remove them as part of the repair and say so.
- **Interrupted syscalls leave no stuck process.** After a timeout kill, `ps` shows
  nothing — absence of a hung process is not evidence the wedge is gone; only the
  step-6 control is.
- **Report the collateral damage you caused.** If a script you wrote (or handed over)
  wedged a host service, say it plainly with the cause and the fix command — do not
  file it as an unrelated observation.
