# Restart-window prep

_Use when handing a reboot or OS-update window to the owner._

An ask whose answer is "reboot the machine" or "apply the OS update" costs the most
when it is handed over unprepared: the reboot also drops whatever does not come back
by itself, and the human finds out afterwards. Run the audit **first**, so the ask is
"reboot when convenient", not "reboot and then repair".

Use when a drift or health card names a pending OS update, when a restart window is
being scheduled, or when an ask you are about to hand over implies a reboot.

## 1. Pre-flight: what a reboot interrupts, and what returns

- **Live work that would lose a turn** —
  `curl -s http://127.0.0.1:7705/api/overview.txt | head -3` (`working` episodes lose
their turn; `idle`/`done` panes lose nothing), plus
  `pgrep -fl 'claude -p|claude --bg'` for daemons and dispatches. A window with zero
`working` is cheap — say so, that is what makes the ask easy to accept.
- **LaunchAgents** — `ls ~/Library/LaunchAgents/` and
  `launchctl list | grep -E 'jkrumm|hermes|herdr|colima'`; a `RunAtLoad` agent returns
at login, which the mini's boot posture is what makes true with nobody present
(`pmset -g | grep autorestart`, `fdesetup status`).
- **Containers: the restart policy decides, not what the compose file looks like it
  intends.**
  ```bash
  for c in $(/opt/homebrew/bin/docker ps --format '{{.Names}}'); do
    printf '%s %s\n' "$c" "$(/opt/homebrew/bin/docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$c")"
  done
  ```
  Anything other than `always`/`unless-stopped` stays down until someone starts it.

## 2. Fix what the reboot would break, then verify the fix

`docker update --restart unless-stopped <container>` changes the **live** container and
survives a real reboot (confirm with
`docker inspect -f '{{.HostConfig.RestartPolicy.Name}}'` after the machine is back).
The compose file in the owning repo may still declare `no`: that divergence is the
owner's call — report it, do not edit the repo for it.

## 3. Deliver the ask through the present-human queue, not another card

A restart ask is person-only work: it needs root and a human. Restating it in chat is
not delivery — the queue's push is.

```bash
cd ~/SourceRoot/dotfiles
TEXT="$(cat /tmp/ask.txt)"; ./scripts/ask-human.sh ask "$TEXT"   # pushing is the DEFAULT
```

- **Text-only (no `--cmd`) gets the informational dialog** and resolves `done` when
  clicked; use it for work that must happen on *another* host.
- **`--cmd` executes on the MacBook**, never on the host the ask was enqueued from — so
  never attach a mini-targeted command, and note that a root/sudo step cannot run from
  this queue at all (`sudo -n` refuses). Put the exact command **in the text** for the
  human to run on the right host.
- **Keep it short**: one line of why, the exact `sudo softwareupdate …` line, and where
  the detail lives. Build a multi-line body in a file and pass it as a variable — the
  harness's command wrapping eats inline quoting and can execute backticked fragments.
- **Exit codes tell you whether it landed**: `69` ssh unreachable, `75` dialog
  unanswered/timed out — both leave the request pending and fire the Slack hook; only
  then is a chat reminder the right fallback.
- **A `done` in the `.res` is an acknowledgement, not evidence.** The push resolves the
  moment the human clicks, whatever he does next — verify the effect on the target
  (step 4) before reporting the ask as answered.

## 4. After the reboot — verify the work, not the ack

```bash
uptime; sw_vers
launchctl list | grep -E 'jkrumm|hermes' | awk '{print $1,$3}'   # '-' in col 1 = loaded, not running
docker ps --format '{{.Names}}|{{.Status}}'                     # "Up N minutes" + healthy
curl -s http://127.0.0.1:7735/health
```

A post-boot load average in the 50-80 range is the agent herd starting, not a fault;
re-check before calling it one.

## 5. Ordering a macOS update

- `softwareupdate -l` marks the restart requirement per item (`Action: restart`).
  Safari and Command Line Tools install **without** a restart (root only).
- **CLT/Safari first.** A pending Command Line Tools update is what wedges a
  source-built formula in a brew mass upgrade (ruby at ~100% CPU, idle `build.rb`
  child, empty `~/Library/Logs/Homebrew/<formula>/` log, only a *newer Command Line
  Tools release is available* warning to go on).
- `make brew-upgrade` **after** the OS step, then `drift-check.sh --no-push`.
- A **major** macOS version bump is an owner decision on the machine that hosts the
  agents — never bundle it into "apply the pending updates".
- The drift checker counts every `RecommendedUpdates` entry and has **no ignore/ack
  mechanism**, so a major upgrade the owner declines keeps the line `✗` indefinitely.
  Say that plainly and offer the choice (install it, or make the line informational)
  instead of re-reporting the same red page.

## Pitfalls

- **Verify the target machine before repeating the card's ask.** A recurring "still
  waiting on you" card is a snapshot; the reboot may already have happened minutes
  earlier (`uptime`, `sw_vers`, the applier's own stamp). Relaying the card as
  outstanding work after the work landed is the failure this audit exists to prevent.
- **Do not schedule the window for him.** Give the current state, the commands, the
  ordering, and what a reboot would cost right now — the timing is his.
- **A restart ask needs the audit attached**, in the queue text *and* the task tracker;
  a bare "apply the updates" leaves him to discover the two containers that did not
  come back.
