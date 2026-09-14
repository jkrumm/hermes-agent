---
name: sudo-handoff
description: Use when a change needs root the agent cannot sudo.
version: 1.0.0
metadata:
  hermes:
    tags: [sudo, root, mini, macos, launchdaemons, privileged, handoff, human-queue, app-removal]
    related_skills: [human-queue, homelab-ops, headless-secrets]
---

# Root change handoff

Use when the work needs root on the mini (or any host) and there is no
passwordless sudo: removing a root-owned app bundle, deleting a
`/Library/LaunchDaemons` plist, touching `/Library/Audio/Plug-Ins/HAL`, anything
owned `root:wheel`. Also the right shape when a queue request or an agent on the
mini proposes a root command.

## The rule

The agent does not get root on the mini. The gateway refuses a password piped to
`sudo -S` (brute-force guard) and the mini has no passwordless sudo. Do not route
around either one — no `osascript … with administrator privileges`, no `expect`,
no password written to a file, no re-running the command from the MacBook's TTY
over an ssh hop. The human runs it; the agent's job is to make that one command
trivial, safe and idempotent.

## Procedure

1. **Confirm the class before writing anything.** `sudo -n true` returning
   "a password is required" establishes it; `ls -ld <path>` confirms the target is
   `root:wheel`. Both are read-only and cheap.
2. **Inventory beyond the request.** The named paths, plus the siblings a request
   never lists: daemons whose app is gone (`/Library/LaunchDaemons/com.<vendor>.*`,
   `/Library/LaunchAgents`), user-level data (`~/Library/Application Support/<vendor>`,
   `Group Containers`, `Caches`, `Preferences`, `Saved Application State`,
   `HTTPStorages`), HAL plug-ins. `du -sh` the user data and `ls -lt` the logs to
   say whether the app was ever really used. A request naming five paths is not a
   claim that only five exist — report the extras and fold them in.
3. **Write the script on the host that owns the files**, at `~/<task>.sh`, from the
   template at the end of this file. The request's own shape — MacBook →
   `ssh mini "echo $PW | sudo -S rm -rf …"` — is exactly the blocked pattern; the
   staged script replaces it, it does not reproduce it.
4. **Hand over exactly one command:** `sudo bash ~/<task>.sh`. No multi-step
   instructions, no interactive prompts inside the script.
5. **Push it, never close it.** The request stays open until a human has actually
   run it. Enqueue the MacBook-side one-liner and trigger the approval dialog
   yourself — the password is read on the MacBook (Touch ID) and reaches sudo on
   stdin, never argv:
   `bash ~/SourceRoot/dotfiles/scripts/ask-human.sh ask "<what, why>" --cmd 'ROOT_PW=$(op read "op://Private/mac-mini-server/password" --account tkrumm) && printf "%s\n" "$ROOT_PW" | ssh mini "sudo -S -p \"\" bash /Users/jkrumm/<task>.sh"' --push`
   (or `ask-human.sh push <id>` for an existing request). Exit 75 = unanswered,
   the request stays pending for `make human-queue`. **Never `resolve` a handoff
   as `done`** — that reports work nobody did and hides it from the human's queue
   (2026-09-14: a Teams removal closed this way showed "nothing pending").
6. **Report a handoff as a handoff.** Not "app removed" — "script staged, one
   command left for you", with what it removes and what it deliberately leaves.

## Pitfalls

- **Never test the sudo path by attempting it.** A refused `sudo -S` is a blocked
  call, not a probe that teaches something; the guard is the answer.
- **A daemon plist is not just a file.** `launchctl bootout system/<label>` before
  removing it, or the job keeps running until reboot and the plist reappears on
  the next vendor install.
- **Core Audio caches the HAL driver list at boot.** After removing a
  `*.driver` under `/Library/Audio/Plug-Ins/HAL`, `killall coreaudiod` — otherwise
  the entry survives the file and the device stays visible.
- **The big win is usually user-level and needs no sudo at all.** A root-owned app
  bundle is a few hundred MB; its `~/Library/Application Support/<vendor>` tree can
  be GBs. Always check it and include it, and say the size in the report.
- **`make human-queue-resolve NOTE=…` dies on shell metacharacters.** The target
  interpolates `$(NOTE)` unquoted into `bash … resolve <id> $(NOTE)`, so a note
  containing parentheses — or `;`, `&`, `|` — makes `/bin/sh` abort with a syntax
  error and writes nothing, while the pending count quietly stays at 1. Keep notes
  to plain words, dashes and colons, or bypass the target:
  `ssh iumac 'bash ~/SourceRoot/dotfiles/scripts/human-queue.sh resolve <id> "<note>"'`.
- **Verify absence, not the exit code.** End the script with a check over the
  target list that prints anything still present; a `rm -rf` on a path that was
  never there exits 0 too.
- **Leave the out-of-scope orphans visible.** Vendor daemons with no installed app
  are worth removing, but say which ones you touched and which you left — an
  unrelated vendor helper is not yours to delete on another app's request.

## Template — `~/<task>.sh`

Copy, fill the lists, hand over `sudo bash ~/<task>.sh`. Encodes the four design
rules: root guard, bootout before plist removal, `[ -e ]`-guarded `rm` so reruns
are safe, and a verify block that prints what is still present.

```bash
#!/bin/bash
set -uo pipefail

[ "$(id -u)" -eq 0 ] || { echo "!! run with sudo: sudo bash $0"; exit 1; }

U=/Users/<user>   # the human account whose ~/Library leftovers are in scope

# --- 1. unload supervised jobs before deleting their plists -------------------
DAEMONS=(
  # com.example.UpdaterDaemon
)
for d in "${DAEMONS[@]:-}"; do
  [ -n "$d" ] || continue
  launchctl bootout "system/$d" 2>/dev/null && echo "booted out: $d" || echo "not loaded: $d"
done

# --- 2. root-owned paths -----------------------------------------------------
ROOT_TARGETS=(
  # "/Applications/Vendor App.app"
  # "/Library/LaunchDaemons/com.example.UpdaterDaemon.plist"
  # "/Library/Audio/Plug-Ins/HAL/VendorAudio.driver"
)
for t in "${ROOT_TARGETS[@]:-}"; do
  [ -n "$t" ] || continue
  if [ -e "$t" ]; then rm -rf "$t" && echo "removed: $t"; else echo "absent:  $t"; fi
done

# --- 3. user-level leftovers (often the largest win) -------------------------
USER_TARGETS=(
  # "$U/Library/Application Support/Vendor"
  # "$U/Library/Group Containers/XXXXXXXXXX.com.vendor"
  # "$U/Library/Caches/com.vendor"*
  # "$U/Library/Preferences/com.vendor"*
  # "$U/Library/Logs/Vendor"*
  # "$U/Library/HTTPStorages/com.vendor"*
  # "$U/Library/Saved Application State/com.vendor"*
)
for p in "${USER_TARGETS[@]:-}"; do
  [ -n "$p" ] || continue
  [ -e "$p" ] && rm -rf "$p" && echo "removed: $p"
done

# --- 4. cached kernel/audio state -------------------------------------------
# killall coreaudiod   # after removing a HAL driver; the list is cached at boot

# --- 5. verify ---------------------------------------------------------------
echo
echo "== verify =="
left=$(ls -d "${ROOT_TARGETS[@]:-}" 2>/dev/null)
if [ -n "$left" ]; then echo "STILL PRESENT:"; echo "$left"; else echo "OK: nothing left from the target list"; fi
echo "-- remaining vendor daemons (out of scope unless named above) --"
ls /Library/LaunchDaemons/ | grep -i '<vendor>' || echo "none"
```
