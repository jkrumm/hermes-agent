---
name: devhost-maintenance
description: Use when maintaining the mini's host state (brew, pins).
version: 1.0.0
metadata:
  hermes:
    tags: [mini, devhost, maintenance, brew, pin, drift, upgrade, launchd, collie, uptime-kuma]
    related_skills: [homelab-ops, warden, warden-item-closure, claude-dispatch]
---

# Dev-host maintenance — the mini's own host state

The mini runs herdr, colima, sideclaw, Hermes, Caddy and every dev door, so its
*host* state — formulae, version pins, LaunchAgents, the OS — has its own
notice→apply loop, and the appliers are deliberately interactive. This skill is
that loop. `homelab-ops` owns container/monitor incidents, `warden` owns the
card's state, `claude-dispatch` owns repo work.

## The loop: notice vs apply

| Half | Command | Contract |
|-|-|-|
| Notice | `cd ~/SourceRoot/dotfiles && ./scripts/drift-check.sh --no-push` | Reports only, fixes **nothing**. `✗` = past `DRIFT_GRACE_DAYS=14`; `~` = drifted but inside grace. The daily agent pushes to the Kuma monitor `MacMini Drift - Push`; `--no-push` is the on-demand read |
| Apply, tool pin | `make collie-upgrade` | Resolves the newest tag, prints scope verdict + changelog + diffstat, then on `y` bumps the pin, reruns `collie-setup`, and commits locally |
| Apply, formulae | `make brew-upgrade` | Converges pins, upgrades outdated formulae, then **asserts** its invariants |

Read the live drift report before believing a card: only the `✗` line drives the
page, and each `~` line has its own 14-day clock from first sight. Say which line
actually pages instead of relaying the whole list.

## Driving an interactive applier (a pty, never the env hatch)

The appliers refuse without a TTY unless an explicit-yes env var is set, because
the prompt **is** the review. Drive it:

1. `terminal(background=true, pty=true, timeout=1200)` on the applier target.
2. Wait for `apply? [y/N]`, then read the printed scope verdict, changelog and
diffstat out of the process log — that is the review material.
3. `process_manage(action='submit', data='y')`.
4. Wait for exit. The applier rolls the pin back itself if its own assertions
   fail, and deliberately leaves the `git push` to a human — decide whether to
   push, and verify afterwards that the pin and the running service moved.

The explicit-yes env var exists for a non-TTY caller; it is not a way to skip the
review.

## Verification after any applier

```bash
./scripts/drift-check.sh --no-push                  # the line is gone
herdr plugin list --json                            # installed version / ref
curl -s -o /dev/null -w '%{http_code}\n' --max-time 5 http://127.0.0.1:8787/         # bridge alive (200)
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example.com' http://127.0.0.1:8787/api/snapshot   # hardening held (403)
brew list --versions <formula>
curl -s http://127.0.0.1:7735/items/<event-id>      # warden item state
```

## Pitfalls

- **A herdr-spawned plugin action gets a minimal environment — resolve tools by
  absolute path.** The applier's `setup` target runs from herdr's spawn, so no
  login-shell PATH: `~/.bun/bin` and `/opt/homebrew` are simply absent. Export the
  bin dir in the *same* command that runs the applier
  (`export PATH="$HOME/.bun/bin:$PATH"; make <target>`), and make sure **both**
  `bun` and `bunx` resolve — a `bun run typecheck` that shells out to `bunx` dies
  `command not found` (exit 127) when the shim is missing, which reads exactly like
  a repo defect and is not one. If the shim really is absent, restore it
  (`ln -sfn bun ~/.bun/bin/bunx`) rather than working around it in the applier.
- **A pinned formula is an unclearable drift line.** `brew upgrade <formula>`
  refuses while it is pinned, and the brew applier only re-pins its own held list —
  so a reported `fix: make brew-upgrade` can never apply. Check
  `ls /opt/homebrew/var/homebrew/pinned/`; if no script in any repo creates that
  pin, it is an unowned hand pin: `brew unpin <f> && brew upgrade <f>`, then
  re-check. Report the skew a formula upgrade leaves: a root LaunchDaemon keeps the
  old binary until a restart, which needs sudo.
- **Never let two mass upgrades coexist.** Brew has no mutex across
  `brew upgrade` invocations; the second run spins at ~100% CPU on the first's
  formula locks with no output, and both may interleave installs. Before starting
  one, look for an existing run (`pgrep -f brew-upgrade.sh`, and the unattended
  log under `~/Library/Logs/`) — let the older one finish and kill the duplicate,
  not the incumbent.
- **A wedge inside `brew upgrade` looks like silence; a source build is the usual
  cause.** Tell: the parent ruby at ~100% CPU while its `build.rb` child idles at
  0% on a pty (`ps -Ao pid,ppid,time,%CPU,command`), an **empty**
  `~/Library/Logs/Homebrew/<formula>/` build log, and
  `Warning: A newer Command Line Tools release is available` just before. That
  warning is the diagnosis — the source build is waiting behind a pending OS/CLT
  update and will not finish. Kill the run, upgrade the one formula you need
  directly, and do the OS restart window **before** the next mass upgrade.
- **A hand-closed Warden card can come back on its own.** A new occurrence
  reopens a `closed` row, and the loop then dispatches a fresh episode against the
  *captured* state from before your fix. Verify the live condition first, then
  `./scripts/warden abort <event-id> --why "fixed and verified (<version/commit>);
  this brief's captured state predates it"` — `abort` cancels the job and closes
  the item in one move, which is cheaper than paying for a verdict on work already
  done.
- **Write multi-line command bodies to a file, never into an inline quoted
  heredoc.** `gh issue create --body "$(cat <<'EOF' … EOF)"` loses its quoting to
  the harness's command wrapping, so backticked fragments in the body are executed
  as shell — a stray applier has been launched mid-report that way. Use
  `write_file` for the body and pass `--body-file <path>`.

## Report shape

Verdict first, in German: which line was actually paging, what shipped, and what
is still the owner's. One line per finding, evidence only where it changes his
next move. Name what you did **not** do — the push you left to him, the restart
that needs a human — and stop there.
