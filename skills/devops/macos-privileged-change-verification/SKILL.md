---
name: macos-privileged-change-verification
description: Use when verifying a privileged macOS change landed.
version: 1.0.0
metadata:
  hermes:
    tags: [macos, verification, tcc, launchctl, root, removal, human-queue]
    related_skills: [sudo-handoff, human-queue, homelab-ops]
---

# Verifying a privileged macOS change

Use when a root-level change on the mini (or any Mac) is claimed to be done — an
app removal, a `LaunchDaemon` unload, a HAL driver delete — and you must report
whether it really happened. Also use it before reporting a human-queue request as
resolved. The companion skills `sudo-handoff` (staging the root script) and
`human-queue` (draining the queue) cover the other halves.

## Procedure

1. **Read the resolution record before anything else.** A resolution is a claim by
   whoever wrote it, not evidence. On the mini the queue lives at
   `${XDG_STATE_HOME:-$HOME/.local/state}/human-queue`:
   ```bash
   D="$HOME/.local/state/human-queue"; cat "$D/<id>.req"; cat "$D/<id>.res"
   ```
   `status: done` with an `output_tail` mentioning out-of-band execution means a
   **human** did it — say that and take no credit. Compare `ran_at` against the
   request's `created` and against now: a resolution written a minute after
   creation, before your walk started, is not your action.
2. **Check the paths on the host.** One `[ -e ]` per path; absence is the proof:
   ```bash
   for p in "/Applications/<Vendor>.app" /Library/LaunchDaemons/com.<vendor>.*.plist \
            /Library/Audio/Plug-Ins/HAL/<Vendor>.driver "$HOME/Library/Application Support/<Vendor>"; do
     [ -e "$p" ] && echo "PRESENT: $p" || echo "gone: $p"
   done
   ```
3. **Check the service table, not just the plist.** A removed plist with a still
   loaded job is a half-removal:
   ```bash
   launchctl print system/<label>     # 'Could not find service … in domain for system' = gone
   launchctl list | grep -i <vendor> || echo none
   ls /Library/LaunchDaemons/ | grep -i <vendor>   # what is left, incl. out-of-scope orphans
   ```
4. **Report in three buckets:** removed+verified, deliberately left (out of scope,
   with size), and anything that could not be removed with the reason. "Done" must
   be auditable without re-reading your transcript.

## Pitfalls

- **`ls`/`du`/`xattr` lie on TCC-gated paths; `stat` and `[ -e ]` do not.** On a
  vendor sandbox container (`~/Library/Group Containers/<TEAMID>.<vendor>.*`),
  `rm -rf`, `rmdir`, `mv`, `ls` and `du` die with `Interrupted system call`
  (`Errno 4`) while `stat` and `ls -ld` answer normally and `[ -e ]` still returns
  true. That is TCC refusing the agent's process, not a permissions or ownership
  problem — root does not fix it. Do not retry the delete and do not put such a
  path in a root script's expected-to-disappear list. Get its size with `stat`,
  report it as left behind and negligible, and move on. A container that survives
  is not a failed removal.
- **Test whether the gate is vendor-wide before blaming the app.** If sibling
  containers of the same sandbox group fail identically, the block is TCC and
  vendor-wide, and the honest report says so instead of implying a stuck file.
- **A queue list can show an already-resolved request as pending.**
  `make human-queue-list`, `make human-queue-count` and the interactive walk read
  the mini's queue over the ssh hop and may still offer a request whose `.res`
  exists. Ground truth is the `.res` on the mini.
- **Never re-act on an already-resolved request.** For a resolved-but-listed
  request, `q` out of the walk: `a`/`already done` writes a second resolution on
  top of the human's, and `r` re-runs a root command that already ran. Then verify
  the effect and report it as resolved out of band.
- **A pending count of 0 is not proof of *your* action.** Read the `.res` for the
  request you were told about and attribute the resolution to whoever wrote it.
- **Do not stop at the exit code.** `rm -rf` on a path that never existed exits 0;
  a script that reports `OK` can still have skipped a target it could not read.
