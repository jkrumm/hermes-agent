---
name: supervised-job-retirement
description: "Use when a supervised job runs against a dead dependency."
version: 1.0.0
metadata:
  hermes:
    tags: [launchd, keepalive, brew-services, retirement, decommission, crash-loop, log-growth, verification, macos]
    related_skills: [supervised-restart-forensics, homelab-ops, macos-privileged-change-verification]
---

# Retiring a supervised job

Use when a `KeepAlive` / `RunAtLoad` job (launchd agent, brew service, systemd unit) is
**faithfully restarted forever against something that no longer exists** — a host that was
decommissioned, a service that was migrated away, a credential that was retired. The
supervisor is doing its job; the job is pointless. The tell is a log that only ever grows
with one connection error, at a steady cadence, for as long as the machine has been up.

Diagnosing *why a restart happened* is `supervised-restart-forensics`. This skill is the
other direction: **proving the dependency is gone and then stopping the job for good**,
reversibly, with evidence that it stayed stopped.

## Procedure

1. **Read the log's whole shape, not its tail.** `wc -l`, `du -h`, the file's birth time
   and `mtime`, then `tail -200 | sort | uniq -c | sort -rn`. A client that has logged the
   *same two lines* N hundred thousand times since the file was born is a loop, not an
   incident — and the birth time dates it. A log of tens of megabytes on a service nobody
   uses is itself the finding; say the size and the rate.
2. **Confirm the dependency is genuinely gone, at the authoritative source.** A resolver
   on one host answering `NXDOMAIN` proves nothing about the zone. Query the zone's own
   nameservers:

   ```bash
   dig +short <zone> NS
   dig @<ns1> <host> A          # want NXDOMAIN here, not just locally
   ```

   Then rule out a wildcard, which would make every name resolve and hide the removal:
   `dig +short @1.1.1.1 <random-nonsense>.<zone>` — empty means no wildcard.
3. **Date the decommission from git, not from memory.** The removal commit is the
   evidence that this is deliberate:

   ```bash
   for r in ~/SourceRoot/<candidate repos>; do
     (cd "$r" && git log --oneline --all -S "<service>" | head -5)
   done
   ```

   `-S` finds the commit that added *or* removed the string; read the subject line to tell
   which (`chore(<svc>): remove … transition complete to <replacement>`). Also check the
   other machines' stacks — the client may be the last thing on the estate still
   referencing it.
4. **Check the client is actually running before retiring it** — `pgrep -fl <binary>` and
   `ps -o pid,ppid,lstart,etime -p <pid>`. A `ppid` of 1 plus a long `etime` is the
   supervisor's own child, and it also proves the client has been working, not hung.
5. **Retire it in two parts, and do not skip the second.** `bootout` stops it now;
   `disable` stops it coming back at the next login or reboot.

   ```bash
   UID=$(ssh <host> 'id -u')                       # read it — do not assume 501
   ssh <host> "launchctl bootout gui/$UID/<label>"
   ssh <host> "launchctl disable  gui/$UID/<label>"
   ssh <host> "launchctl print-disabled gui/$UID | grep <label>"   # "<label>" => disabled
   ```

   Leave the plist in place. `disable` is the reversible switch; deleting the file
   destroys the record of what was there and of how to bring it back.
6. **Verify by log-growth delta, never by process absence.** A `KeepAlive` job respawns
   between two `pgrep`s, so an empty process table proves nothing:

   ```bash
   a=$(stat -f%z <log>); sleep 15; b=$(stat -f%z <log>); echo "delta=$((b-a))"
   ```

   Zero across a window longer than the job's own restart cadence is the proof. Report
   the delta, not "the process is gone".
7. **Report the retirement as reversible and name the undo.** State the label, the host,
   the log volume that stops accruing, and the one command that brings it back
   (`launchctl enable gui/<uid>/<label>` + `bootstrap`). A retired job is a decision the
   owner may want to reverse; make that cheap.

## Pitfalls

- **The per-user launchd domain id is not always `501`.** Read it with `id -u` on the
  target host. Booting out against the wrong uid fails
  `Boot-out failed: 125: Domain does not support specified action` — and because
  `launchctl list` keeps showing the job with a nonzero last-exit code, the failure reads
  exactly like "still running". Retry against the real uid before concluding anything.
- **`brew services stop <formula>` is not always available, and its refusal is not a
  dead end.** A formula from an untrusted tap is refused outright (`Refusing to load
  formula … from untrusted tap`), and a plist brew no longer lists cannot be stopped
  through brew at all. Go to `launchctl` directly — it works whoever wrote the plist.
- **A crash loop against a dead dependency is not an outage to repair.** Do not restart
  the client, do not "fix" its config to point somewhere else, and — when the dead thing
  is a repo — do not clone the repo to make a downstream tool happy. Repairing the client
  re-arms the loop; the finding is that the client should stop existing.
- **A log nobody reads still costs.** Quote the size and the daily growth rate in the
  report. It is usually the most concrete consequence available, and it is the reason the
  retirement is worth doing even when nothing is visibly broken.
- **One host's DNS answer is not the zone's.** A local resolver, a cached negative
  answer, or a `dnsmasq` wildcard can all produce a wrong answer in either direction.
  Only the authoritative nameserver settles whether a name was removed.
- **A retired job's plist can be regenerated.** Anything that re-installs the package
  (a `brew` upgrade, a setup script) may write the plist back and re-enable it. Say so in
  the report when the client was installed by a package manager, so a recurrence is not
  mistaken for the fix having failed.

## Report shape

Verdict first: what the job is, what it was talking to, and that the dependency is gone
(with the decommission commit). Then one line each for the log volume and rate, the
retirement action taken, and the log-growth delta that proves it. Close with the undo
command and anything you deliberately left in place.
