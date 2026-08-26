---
name: homelab-ops
description: Diagnose and remediate homelab / VPS / Mac Mini infrastructure through the bounded `hermes-ops.sh` verb dispatcher — monitors down, unhealthy or restart-looping containers, cron failures, push-monitor heartbeat gaps, uptime-kuma config corruption, deploy drift. Read-only triage is free; every mutation is a named verb needing --confirm and --why. Use for "#alerts" messages, "what's down", "is everything up", "why is X red", "restart Y", "redeploy Z".
version: 1.1.0
metadata:
  hermes:
    tags: [homelab, vps, mini, alerts, alert, incident, outage, down, infrastructure, infra, uptime-kuma, uptimekuma, monitor, monitors, docker, container, containers, unhealthy, restart, deploy, redeploy, cron, heartbeat, push-monitor, launchd, ops, devops, sync, drift]
    related_skills: [argo-api, capture]
---

# Homelab Ops

One bounded dispatcher for every infrastructure action:

```
~/.hermes/scripts/hermes-ops.sh <verb> [args] [--json] [--why "<reason>"] [--confirm]
```

Run `~/.hermes/scripts/hermes-ops.sh help` for the authoritative verb list — this
file explains *when* to reach for each one, the script itself is the contract.

## Operating rule

1. **Diagnose with Tier A.** Read-only, no approval prompt, no side effects. Use
   them freely and early; never guess when a verb can answer.
2. **Mutate only with Tier B.** Every Tier B verb needs `--why "<reason>"` **and**
   `--confirm`. Without `--confirm` it prints the exact plan and changes nothing —
   run it bare first, show Johannes the plan, then re-run confirmed.
3. **Anything not covered by a verb gets escalated, never improvised.** Do not
   compose raw `ssh`/`docker`/`sqlite3`/`launchctl` for ops work. State the
   observation, the failure class, and the precise command you recommend — and
   say why you are not running it.

`--json` gives exactly one JSON object per invocation, success or failure (a
failure carries `ok:false` + `exitCode` in that same object). Use it when you need
to parse; use plain output when you need to quote a summary into Slack.

Exit codes: `0` ok · `2` precondition failed · `3` remote failed · `64` usage error.
Every invocation is audited to `~/Library/Logs/hermes-ops.log`, including dry runs.

Hosts are `homelab` and `vps`. Read-only *data* questions (metrics, tasks, weather)
belong to the `argo-api` skill; this skill is health, incidents and change.

For a named error-string / job-name → root-cause → verb lookup beyond the
tables below, see `references/alert-patterns.md` — check it before improvising
a diagnosis for anything that looks like a recurring alert shape. Dev-vhost
DNS troubleshooting (`mini.jkrumm.com` and friends) is `references/cloudflare-dns.md`.
A mini LaunchAgent restart alert — reload vs crash, and what a benign restart
still costs — is `references/launchd-restart-triage.md`. Reading the mini's
kernel memory-pressure signal correctly (WARN/CRITICAL vs swap, false-friend
log lines) is `references/macos-host-pressure.md`.

## Tier A — diagnosis (free)

| Verb | Answers | Read the output as |
|-|-|-|
| `status` | "Is anything actually down?" — start here, always | `leafDown` is the honest outage count (leaf monitors only). Docker counts come from argo talking to Docker **directly** — all-running + monitors-down is the classic stale-monitor tell |
| `monitors [filter]` | Per-monitor state, name-filtered | `uptime1d`/`uptime30d` date the breakage: fresh outage ≈ 0.0x on 1d with a healthy 30d; `type=group` rows cascade from children and are symptoms |
| `containers <host>` | Container state, health, restart count | A climbing `restarts` with `state=running` is a crash loop, not a healthy container |
| `logs <host> <container> [n]` | What the container says (default n=200) | Find the OK→ERROR transition, not just the tail. Container clocks are +02:00; argo/Slack are UTC |
| `alerts [n]` | Recent `#alerts` messages, newest first | For a burst pull 40–60, not 10 — a short window hides which incident you are in. Timestamps are UTC |
| `env-check` | "Can `op run` resolve every ref on homelab + vps?" | Failure lists the **dangling 1Password item names**. This is the single highest-leverage check in the fleet — see Traps |
| `sync-drift` | "Is what's committed what's running?" | Read `inSync` on the `deployedTruth: true` rows. `ok:false` means the clone could not be probed — unknown, *not* clean |
| `kuma-db <preset> [args]` | Fixed uptime-kuma DB reads, no free-form SQL | `monitor-config` (empty hostname / `http://:port/` = corruption fingerprint) · `heartbeats <id>` (last 25 beats; last `1`→first `0/2` dates the break) · `push-tokens` (prefix only) · `created-dates` (a monitor born mid-incident was hand-added) |
| `heartbeat-gaps` | "Which push monitors never got a heartbeat?" | `uptime1d=0` **and** `uptime30d=0` = the monitor exists, the pusher does not. Fix the pusher; never delete the monitor |
| `uk-dry-run` | Preview the uptime-kuma monitor sync | Previews the homelab checkout **as deployed** — it does not pull. Use `sync-drift` to learn whether that checkout is stale |

## Tier B — remediation (`--why` + `--confirm`)

| Verb | Use when | Not a fix for |
|-|-|-|
| `restart-kuma` | Containers all healthy but many monitors down — uptime-kuma is holding dead client connections (Docker bridge IPs changed under it, or a stale MySQL pool) | A real outage. If containers are genuinely down this only hides the clock |
| `uk-sync` | Monitor configs are corrupted (empty hostnames, empty bearer) and must be re-applied from the declared source | A stale monitor cache — that is `restart-kuma`. Hard-aborts if `env-check` fails, by design |
| `restart <host> <container>` | One container is wedged, unhealthy, or stuck mid-restart, and its logs show no code-level fault | A crash loop with a traceback — restarting resets the counter and buys nothing. Escalate |
| `redeploy <host> <stack>` | The running stack is behind the deployed truth, or containers were lost/orphaned | `homelab`: the `homelab` stack. `vps`: `networking`, `infra`, `monitoring`. `homelab-private` is deliberately absent (its deploy is a full VPN cycle) |
| `cron-rerun <job>` | A host cron missed its window and you want the current run *now* | `vpn-watchdog`, `auto-update`, `garmin-auto-relogin`, `koinsight-stats-push`. Run `env-check` first — a dangling ref makes the rerun fail identically |
| `devhost-health` | A `MacMini * - Push` monitor is red and you want a fresh heartbeat without waiting a launchd interval | A genuinely broken mini service — the check reports it, it does not repair it |
| `launchd-repair <label>` | A mini LaunchAgent was booted out of the user domain by a macOS session teardown (KeepAlive can never respawn what was removed) | A loaded-but-broken agent. The verb prints `launchctl print` first and only bootstraps when genuinely absent |

## Diagnostic playbook

Every path ends in a Tier B verb or an escalation. Nothing ends in raw shell.

### Uptime-kuma monitors down

1. `status` — take `leafDown`, the `downMonitors` list, and the docker counts.
2. Containers all running while monitors are down → uptime-kuma has stale client
   connections. Recurs after the nightly image-update run recreates containers onto
   new bridge IPs. → **`restart-kuma --why "…" --confirm`**.
3. Down monitors show `connect ECONNREFUSED` on an *empty-hostname* URL, or auth
   monitors return 401 → config corruption, not an outage. Confirm with
   `kuma-db monitor-config`, then **`env-check`** (a sync while `op run` is broken
   re-corrupts everything), then `uk-dry-run`, then **`uk-sync --why "…" --confirm`**.
4. `env-check` failed → **escalate**: 1Password is Johannes's to fix. Report the
   dangling item names verbatim.
5. Nothing matches → check `references/alert-patterns.md` for a named pattern
   first, then **escalate** with the monitor names, their `msg` from
   `kuma-db heartbeats <id>`, and what you ruled out.

### Docker container unhealthy

1. `containers <host>` → find `health=unhealthy` or `state != running`.
2. `logs <host> <container> 200` → locate the OK→ERROR transition.
3. Transient (dependency blip, dead pool, wedged worker) → **`restart <host> <container>`**.
4. Config/image is behind what is declared, or containers went missing → `sync-drift`
   to confirm, then **`redeploy <host> <stack>`**.
5. A code-level fault (traceback, schema error, panic) → **escalate**. Code fixes
   and image rebuilds are not ops verbs.

### Docker restart loop

1. `containers <host>` → `state=running` with a climbing `restarts` is the tell.
2. `logs <host> <container> 200` — a loop repeats the *same* fault every cycle.
3. **Do not restart.** It resets nothing and destroys the log window. Escalate with
   the repeating error and the restart count.
4. Only exception: the loop started right after a deploy and the running config is
   behind the declared one (`sync-drift`) → **`redeploy <host> <stack>`**.

### Cron failure

1. **`env-check` first, always.** All four homelab crons share one `.env.tpl`.
2. Dangling item → **escalate**. Every one of the four is down until it is restored;
   say so, because the alert you got names only one.
3. Env clean → `logs homelab <container>` or the job's own monitor via
   `monitors <name>` to see what it actually reported.
4. A one-off miss → **`cron-rerun <job> --why "…" --confirm`**.
5. The job fails on rerun for its own reasons → **escalate** with its output.

### Push-monitor heartbeat gap

1. `heartbeat-gaps` — if the monitor is listed (`1d` and `30d` both 0) it has
   **never** received a heartbeat: the pusher was never built. → **escalate as dev
   work.** Do not delete the monitor; that silences a real gap in coverage.
2. Not listed → it has history, so this is a gap, not an orphan. `monitors <name>`
   for the uptime ratios and `kuma-db heartbeats <id>` for the last good beat.
3. A `MacMini *` monitor → usually a transient push/DNS blip that self-heals on the
   next interval. To confirm the mini side is healthy now:
   **`devhost-health --why "…" --confirm`**.
4. The push comes from a launchd agent that is gone from the user domain →
   **`launchd-repair <label> --why "…" --confirm`**.
5. The push comes from a host cron → the Cron failure path above.

## Traps

- **Count leaves, not groups.** A group monitor goes down whenever any child does,
  so a `status == 0` filter over all monitors reports a dozen failures for three
  real ones. `status` already counts leaves only — trust it over your own tally.
  Also watch `PENDING` (mid-retry), which a down-filter silently misses.
- **Groups clear last.** After a fix, leaves flip within a check interval but
  top-level groups can take ~10 more minutes. Re-run `status` before saying
  "stable"; groups still clearing is normal recovery, not a second incident.
- **The mini's clone is not deployed truth.** The servers deploy by pulling from
  origin, so origin is what runs and the local checkout is an opinion. An incident
  has already been misdiagnosed as "this monitor isn't declared anywhere" from a
  clone two commits behind the origin that declared it. Use `sync-drift` and read
  the `deployedTruth: true` rows.
- **Committed ≠ live.** A fix can be committed and pushed and still not be running.
  Only `redeploy` and `uk-sync` pull. "I pushed the fix" is not a resolution.
- **`op run` fails wholesale on one dangling ref.** A single renamed or deleted
  1Password item aborts the entire command, so all four homelab crons die together
  and the next monitor sync would write empty hostnames and empty bearer tokens.
  The alert that pages you is three layers downstream. `env-check` is the fast test.
- **A bare monitor sync corrupts configs** — unset variables substitute to `""` and
  get written back into the DB. That invocation is unreachable from here: `uk-sync`
  runs `env-check` as a non-overridable pre-flight and aborts on failure. Never
  reconstruct the raw command to work around that abort; fix the ref instead.
- **Timezones.** Argo and Slack are UTC; container logs are +02:00. Convert before
  correlating, or you will grep an hour that has no lines in it.
- **Monitor ids are strings** in the API (`"150"`, not `150`). Comparing against
  integers matches nothing and prints nothing — which reads exactly like "clean".
- **Absence of an answer is not a clean bill.** `sync-drift` with `ok:false` and a
  `--json` object with `ok:false` both mean "I could not look". Never render that as
  "nothing to see".
- **A direct `op read` on the mini hangs** — same root cause the global secrets model
  documents (headless, no biometric human to answer the prompt). `secrets-run` only
  covers refs seeded into `headless.refs`; an ad-hoc lookup outside that set (e.g. a
  BetterStack or Cloudflare monitoring token pulled for a one-off diagnostic, not
  wired into any service's `.env.tpl`) is not in the cache. Run it via
  `ssh homelab "op read 'op://…'"` instead — never locally.

## What this skill will NOT do

Excluded on purpose. If one of these is genuinely the right move, escalate it with
the exact command — do not reach for raw shell.

| Excluded | Why |
|-|-|
| Direct SQL writes to the uptime-kuma DB | A running uptime-kuma overwrites DB writes from its in-memory cache, and it repairs only half the damage anyway. `uk-sync` supersedes it |
| Stopping a stack (`down`) | Stopping something is never mechanical recovery |
| Redeploying `homelab-private` | Its deploy is a full VPN teardown with exit-country validation — a judgement call, not a redeploy |
| Restarting the Hermes gateway | That is the process running this verb. A gateway restart is a deliberate human action |
| Backup prune / init | Needs a master credential this machine's secrets cache refuses by design |
| Any 1Password write | Credential decisions are Johannes's, not the agent's |
| `git push` from a server | The deploy key is read-only; it would fail |
| Moving or deleting media | Not recoverable, not idempotent, not ops |
| Code fixes, image rebuilds | Repo work with review and history — belongs in a Claude Code session, not an alert response |
| Free-form SQL, command, or URL | The escape hatch that would defeat the entire point of a bounded verb set |

**Escalation shape** — when you land here, give Johannes four things and stop:
what you observed (with the verb output), which failure class it is, the exact
command or change you recommend, and what you have already ruled out.
