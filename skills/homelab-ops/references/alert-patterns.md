# Alert Patterns

Error-string / job-name → root-cause → verb lookup for `#alerts`. This is the
"how do I read this alert" companion to the main `homelab-ops` skill's "which
verb do I run" tables — check here first when a message doesn't obviously map
to a Tier A/B verb, then run the verb the pattern points at. Don't re-derive a
diagnosis from scratch for anything listed here.

Slack channel: `#alerts` (`C0AS1LAUQ3C`) — pull with the `argo-api` `slack`
reference. For a burst pull 40–60 messages, not 10.

---

## BetterStack "New incident for …" — external monitor, not UptimeKuma

**Trigger:** a bare `New incident for <Name>` message in `#alerts` with no emoji,
no URL, no "No heartbeat" wording. The bot user is **Better Stack**, NOT the UptimeKuma webhook (match on the
display name; this repo is public, so the workspace user id is not recorded here).

- **What it is:** BetterStack's external monitor (display name `HomeLab - Uptime`) probes a public homelab URL from outside and posts
  the incident via its Slack integration. This is the *external* view — it can
  fire while every internal UptimeKuma monitor stays green.
- **First check:** the homelab watchdog log
  (`ssh homelab "tail -80 /var/log/homelab_watchdog.log"`) — the watchdog
  polls the same BetterStack monitor and will have logged
  `⚠️ BetterStack still down after 2 retries` + the diagnosis line
  (`External monitor down, internal healthy — external access path issue`) +
  its recovery action (`restarting cloudflared + caddy`).
- **Typical resolution:** the watchdog self-heals within minutes by restarting
  cloudflared + caddy. Verify externally with a public probe
  (`curl -o /dev/null -w "%{http_code}" https://img-origin.jkrumm.com/rs:fit:100/misc/monitor-probe.jpg` → 200).
  cloudflared/caddy logs are usually clean — the blip is on the Cloudflare
  edge or BetterStack's probe network, not the tunnel.
- **Collateral:** while the watchdog is busy with recovery its 10-min push
  heartbeat lands late → `HomeLab Watchdog - Push` (id 41) may flap Pending
  for seconds and self-clear. Harmless; Pending alone does not notify.
- **No ops verb needed.** Do not restart anything — the watchdog owns this
  recovery path. If the watchdog log shows escalation past state 2 (Docker
  restart / reboot path), then escalate.

---

## Scheduler job failure — `torrent-app` transaction bug

**Trigger:** `*Scheduler job failed*` naming `record_speed_history` with
`cannot commit - no transaction is active`.

- **Container:** `torrent-app`. **Source:** `apps/torrent-app/backend/db.py` →
  `_write_tx()`.
- **Bug class:** `conn.execute("BEGIN IMMEDIATE")` sat outside the `try` block.
  When the transaction was lost between `BEGIN` and `COMMIT` (busy timeout
  during `executemany`), `COMMIT` raised uncaught.
- **Fix (already applied upstream — reference only if it regresses):** move
  `BEGIN IMMEDIATE` inside the `try` so `except` catches and rolls back
  `COMMIT` failures too.
- **Deploy:** `redeploy homelab homelab` (rebuild picks up the fix). No
  ops verb reruns a single scheduler job — that's a code fix, not ops.
- **Severity note:** a *different*, low-severity job — `_sync_jellyfin_play_history_job`
  failing with a bare 500 — is Jellyfin's own API misbehaving, not a
  torrent-app bug. The job already handles it gracefully (logs + continues);
  only escalate if it repeats across many runs.

---

## Docker bridge-IP cascade — containers fine, monitors stale

**Trigger:** `ECONNREFUSED` on a Docker bridge IP (RFC1918, `172.x.x.x`)
across many monitors at once — can start with one HTTP monitor and cascade to
20+ within minutes, growing rather than shrinking.

- **Root cause:** Watchtower's nightly run recreates containers (most
  critically the socket proxy). Each recreated container gets a **new bridge
  IP**; UptimeKuma has old ones hardcoded — both its Docker-type monitors
  (proxy IP) and HTTP-type monitors that target container IPs directly.
- **Key diagnostic signal:** `status` shows Docker counts all-healthy
  (argo talks to Docker directly, not through the stale-IP proxy) while
  UptimeKuma reports a growing down count. That mismatch *is* the diagnosis —
  don't chase a real outage.
- **Verb:** `restart-kuma --why "docker bridge IP cascade" --confirm` — clears
  the stale client pool immediately; down count should hit 0 within 2–3 min.
- **Permanent prevention (code change, not ops):** UptimeKuma monitors that
  hardcode a bridge IP instead of the container's DNS name will keep breaking
  on every Watchtower cycle. Flag it, don't hand-edit — the fix belongs in
  `monitors.yaml` + `uk-sync`.
- **Not the same as:** the VPN container stack going down (see next pattern) —
  that needs a real redeploy, this needs only a UptimeKuma restart.

---

## VPN stack down after Watchtower — `make up` in homelab-private

**Trigger:** `gluetun`/`qbittorrent`/`prowlarr`/`flaresolverr`/`torrent-app`/
`shelfmark` show down/exited after a nightly Watchtower run.

- **Distinction from the bridge-IP cascade:** here the containers are
  genuinely stopped, not just a stale UptimeKuma pool — `containers homelab`
  will show `state != running` for the VPN stack, not `running` with stale
  monitors.
- **Root cause:** the VPN stack is deployed from `homelab-private`, not `homelab`,
  and is deliberately excluded from Watchtower. `redeploy homelab homelab` only
  covers the `homelab` stack and will NOT start the VPN containers (verified
  2026-08-07). Its compose details stay in that repo — do not restate them here.
- **Watchdog self-heals first:** `vpn-watchdog` (5-min check, log via
  `logs homelab vpn-watchdog-logs`) logs `VPN unhealthy (running=false,
  health=unhealthy)` + `Consecutive failures: N/3 before self-healing
  attempt`. After 3 consecutive failures it runs its own vpn-cycle; the
  stack typically recovers ~15 min after the Watchtower pass WITHOUT manual
  action (observed 2026-08-07: recovered, all 6 containers running, gluetun
  healthy, monitors back to green). Verify before touching anything.
- **Fix (manual fallback):** full VPN cycle on the private stack:
  `ssh homelab "cd ~/homelab-private && make up"` — gluetun recreate →
  exit-country validation → all VPN dependents + torrent-app rebuild.
  This is the sanctioned path (homelab-private redeploy is deliberately NOT
  an ops verb; `make up` is its safe entry point).
- **Verify:** `containers homelab` shows all 6 running (gluetun `healthy`),
  then `status` → `down=0` (UptimeKuma docker monitors lag a check interval
  or two — up to ~1 min).

---

## VPS Watchtower kills its own socket proxy

**Trigger:** Slack "Watchtower updates on `<container-id>`" repeating nightly,
attachment `dial tcp: lookup socket-proxy-watchtower ... no such host`.
Watchtower's own log shows a nil-pointer panic on the same run.

- **Root cause:** Watchtower found a new socket-proxy image and tried to
  update **every** proxy — including the one it is connected through — via
  its own connection. It SIGTERMs the proxy, loses Docker access mid-run, and
  never recreates it. The proxy sits `Exited (0)`; every nightly run since
  panics on the DNS lookup. A second proxy container can be missing entirely
  from the same incident (dozzle/beszel then lose Docker access too).
- **Diagnosis:** `containers vps` → the socket proxy shows `Exited`; a sibling
  proxy container may be absent. `logs vps watchtower <n>` → `Found new
  tecnativa/docker-socket-proxy image` → `Stopping ... with SIGTERM` →
  `EOF` → repeated `Cannot connect to the Docker daemon` → `Session done
  Failed=N Updated=0`.
- **Verb:** `restart vps socket-proxy-watchtower --why "..." --confirm`
  (restart also starts an exited container), then `redeploy vps monitoring
  --why "..." --confirm` to recreate anything the incident deleted.
- **Permanent prevention (code change, not ops):** exclude the socket proxy
  containers from Watchtower's own update scope — the proxy Watchtower talks
  through must never be a Watchtower update target. Flag it as a `vps` repo
  fix, don't patch it live.
- **Not the same as:** the homelab bridge-IP cascade (containers healthy,
  UptimeKuma stale) or VPS endpoint unreachability from argo (below) — here
  the proxy is genuinely down.

---

## VPS Docker endpoint intermittently unreachable

**Trigger:** `/docker/vps/*` returns a typo-style error, an empty 200, or a
timeout, while UptimeKuma shows the actual VPS services healthy.

- **Root cause:** the VPS `docker-socket-proxy` is unreachable — a monitoring
  gap, not a service outage. The application containers are almost always
  fine.
- **Diagnostic order:** `status` first (a `dockerVps` error is the canary),
  then trust `monitors` over the Docker endpoint — UptimeKuma probes the real
  service ports, not the socket proxy.
- **Don't retry the endpoint repeatedly** — it won't self-heal without a
  container restart. `restart vps docker-socket-proxy --why "..." --confirm`
  is the fix if genuinely needed; otherwise report "Docker API unreachable,
  but all services healthy via UptimeKuma" and move on.

---

## Mac Mini push monitor — heartbeat timeout / dev-vhost DNS FAIL

**Trigger:** `No heartbeat in the time window` for a `MacMini * - Push`
monitor, optionally carrying an embedded `FAIL: dev vhosts: ... resolves to
nothing` message.

- **Root cause:** the mini's health-check LaunchAgent couldn't push to the
  UptimeKuma endpoint, or the push succeeded but an embedded DNS check
  failed. The mini's own services (tailnet, sshd, git) are almost always
  healthy — the failure is in outbound push delivery or DNS resolution, not
  the host.
- **Common failure modes:** transient DNS resolution timeout for the
  UptimeKuma hostname; a brief tailnet/WAN dropout; the dev-vhost record
  failing to resolve from the mini's own resolver (the Cloudflare record
  itself is almost always correct — see `references/cloudflare-dns.md` to
  confirm before assuming a record problem).
- **Verb:** `devhost-health --why "..." --confirm` forces a fresh heartbeat
  without waiting a launchd interval. Usually self-resolves within one
  interval regardless.

## Home Line push / watchdog

**Trigger:** `No heartbeat in the time window` for the home-internet-line
push monitor or its watchdog monitor.

- The **push** monitor reports the line itself; the **watchdog** monitor
  reports the health of the local collector agent — silence on the watchdog
  means the agent is gone, not the line. A watchdog DOWN is the more serious
  signal.
- Almost always a single missed heartbeat window that self-clears on the next
  push (a few minutes).
- **If it does NOT self-clear** (verified 2026-08-06): all three linewatch
  agents (`com.jkrumm.linewatch-{collector,heartbeat,watchdog}`) were booted
  out of the GUI domain — plists exist in `~/Library/LaunchAgents`, overrides
  say `enabled`, but `launchctl print gui/501/<label>` says "Could not find
  service". Classic teardown-then-reboot state; the agents never re-registered
  at login. Tells in the agent logs: `watchdog.exit reason=SIGTERM` /
  collector `event:stopped` at the same second for all three.
  **Fix: `hermes-ops.sh launchd-repair <label> --why "…" --confirm` for each of
  the three labels.** Verify beats resume within ~1 min (`kuma-db heartbeats
  <id>`; Home Line - Push = 207, Home Line - Watchdog = 208). A fresh
  heartbeat with `sample 30s old` + collector cycles = fully recovered.

## Mac Mini — hermes gateway restarted / not answering

**Trigger:** a `MacMini * - Push` heartbeat carries `gateway restarted (N→M,
Terminated: 15)` and/or `hermes gateway not answering` on its port.

- **Usually planned, not an incident.** The gateway restarts deliberately on
  every Hermes config/model change; a Claude Code session working in the
  `hermes-agent` repo doing a kickstart cycle produces exactly this signal.
  Correlate against recent commits in that repo before treating it as a
  crash.
- **Not the same as:** a genuine crash loop (tracebacks in the gateway error
  log, non-zero exits repeating without a correlated config change) — that's
  an escalation, not "wait for launchd to respawn it".
- **Settled vs. climbing — verify before closing:** run
  `devhost-health --why "…" --confirm` for a fresh heartbeat. The output line
  `no restarts (history: <label>=N)` with N unchanged from the alert means the
  restart was a one-off: settled, monitor flips UP on the next interval.
  A fresh `FAIL: <label> restarted (N→M, ...)` with a climbing count means it
  is still crashing: escalate. Applies to any mini LaunchAgent with a
  `Terminated: 15` restart signature (e.g. `com.jkrumm.sideclaw`), not only
  the hermes gateway.
- **sideclaw restarts are usually planned dev reloads.** The Makefile's
  `reload` target runs `bun run build` then
  `launchctl kickstart -k gui/501/com.jkrumm.sideclaw` — kickstart sends
  SIGTERM and respawns, which the devhost-health monitor reads as a restart
  (count climbs, `Terminated: 15`). Any burst of sideclaw restarts whose
  times correlate with edits/builds in `~/SourceRoot/sideclaw` (check `dist/`
  mtime, `server/` mtime, recent commits) is development activity, not a
  crash — the log (`~/Library/Logs/sideclaw.err`) stays clean and the process
  keeps running between SIGTERMs. Close it; no verb needed. Only escalate if
  restarts happen with no repo activity, or the process dies within seconds
  (crash loop) instead of after tens of minutes.

## Mac Mini session teardown — a LaunchAgent vanishes, not crashes

**Trigger:** a `MacMini * - Push` heartbeat reports a local service not
answering, and `launchctl print gui/501/<label>` returns "Could not find
service" (not "not running" — genuinely absent from the domain).

- **Root cause:** macOS session-teardown (`smd`, the Session Management
  daemon) boots a batch of background-managed agents out with SIGTERM after a
  login-state change or crash-reboot — not a crash in the service itself.
  Several unrelated agents typically go together in the same teardown.
- **Fix (no sudo):** `launchctl bootstrap gui/501
  ~/Library/LaunchAgents/<label>.plist` re-registers and starts it
  (`RunAtLoad`). Do **not** use `launchctl load`/a kickstart — `kickstart -k`
  fails on a service that was removed rather than merely stopped, only
  `bootstrap` re-adds it.
- **Reboot variant:** identical symptom right after a fresh boot means the
  agent simply never registered at boot (plist present and valid, just never
  bootstrapped) — same fix.

## Mac Mini reboot cascade — tailnet down, caddy can't bind

**Trigger:** after a mini reboot, `tailscaled not Running` plus `caddy admin
API not answering`, often with transient bridge/LiteLLM failures alongside.

- **Root cause:** Tailscale didn't auto-reconnect after boot. Caddy's
  generated config binds the tailnet IP specifically; while that address
  doesn't exist yet, caddy fails to bind and crash-loops. The other
  transient failures are usually just boot lag on services that self-heal
  within minutes once their own KeepAlive/StartInterval fires.
- **Fix (no sudo):** bring Tailscale up again (`Tailscale up`, using saved
  prefs) — caddy binds successfully on its next respawn.
- **Not the same as:** a tailnet-wide outage (check whether homelab/VPS are
  also unreachable) or a caddy config bug unrelated to the tailnet address.

---

## UptimeKuma MySQL monitor — stale pooled connection

**Trigger:** a `mysql`-type monitor goes down with `Can't add new command
when connection is in closed state`; its group monitor cascades.

- **Root cause:** UptimeKuma's pooled DB client connection went stale
  (`wait_timeout`, a network blip) and the pool keeps handing back the dead
  connection — every check fails identically until the pool clears. The DB
  and the app using it are almost always healthy.
- **Verb:** `restart-kuma --why "stale MySQL pool" --confirm`.

## UptimeKuma pause/resume-all cycle vs. a bad sync

**Trigger:** several unrelated monitors fail at once with *different* error
shapes — connection-refused on monitors with an **empty hostname** in their
URL, auth monitors failing with an invalid/expired token, push monitors
flipping Down→Up a second apart.

- **Two different causes produce the same burst signature — distinguish
  them:**
  1. **A human pause/resume-all cycle** in the UptimeKuma UI re-activates
     monitors that were paused because their configs were already broken.
     Nothing new gets corrupted; it just resurfaces old breakage.
  2. **A bare `sync.py` run** (the config sync run **without** its required
     env-file wrapper) *actively writes* the corruption: unset `${VAR}`
     substitutes to an empty string and gets written into the monitor's URL
     or auth header. This is worse — every affected monitor's config is now
     wrong until re-synced properly.
- **Tell them apart:** a resume burst plus a `monitors.yaml` commit landing
  minutes earlier, plus empty-hostname URLs, means case 2. A resume burst
  with no recent commit and pre-existing broken configs means case 1.
- **Verb:** confirm with `kuma-db monitor-config` (empty hostname / stripped
  auth header is the fingerprint), then `env-check` (a re-sync while `op run`
  is itself broken re-corrupts everything), then `uk-dry-run` to preview,
  then `uk-sync --why "..." --confirm`. `uk-sync` hard-aborts on a failing
  `env-check` by design — don't try to work around that.
- **Verify recovery, in order:** HTTP leaves flip first, the affected push
  monitor (if any) flips on its next cron tick, then **group monitors clear
  last** — a top-level group can lag the leaves by up to ~10 minutes. A
  leaf-only `down: 0` can still hide a not-yet-cleared group; re-check
  `status` before declaring it stable.
- **Never write to the uptime-kuma DB directly** to "fast-fix" an
  empty-hostname URL — a running uptime-kuma's in-memory cache overwrites
  direct writes, and it only fixes the URL, not an expired auth token. Use
  `uk-sync`.

---

## Push monitor created but never wired — `heartbeat-gaps` said unwired, now what

**Trigger:** `heartbeat-gaps` (or a raw `uptime1d`/`uptime30d` both at 0)
flags a push monitor that has *never* received a heartbeat, distinct from one
with real history that just had a gap.

- **Root cause class:** a two-machine deploy where the monitor config landed
  (declared in `monitors.yaml`, deployed) but the pusher side — a script +
  LaunchAgent on the mini that should curl the push URL — was never built.
  The monitor is intentional, not orphaned; deleting it just silences a real
  coverage gap.
- **Escalate as dev work, don't delete.** Building the missing pusher is
  `dotfiles`/`hermes-agent`-repo work (a new script + LaunchAgent + a push-URL
  file under `~/.config/uptime-kuma/`), not an ops verb — say so and let
  Johannes decide whether to build it now.
- **Known wired pushers** (for orientation when a similarly-shaped push
  monitor shows up): the brain-vault sync/backup heartbeats run from
  `dotfiles/brain/brain-sync.sh` (every 5 min, `com.jkrumm.brain-sync`) and
  `dotfiles/brain/brain-backup.sh` (nightly, `com.jkrumm.brain-backup`) — both
  source a shared `kuma-push.sh` helper and treat a missing push-URL file as
  a silent no-op by design ("a monitor must not depend on the thing it
  monitors"), so a missing pusher shows as a red monitor, never a crashed
  script.

---

## RollHook deploy failure — transient 502 on manifest GET

**Trigger:** `:x: Deployment failed: <service>` from RollHook with
`docker pull failed ... unexpected status from GET request to
https://rollhook.jkrumm.com/v2/<service>/manifests/sha256:<digest>: 502 Bad Gateway`.

A different rollout-window artifact — an HTTP health probe 404ing for a few minutes
during a healthy rolling replacement, not a registry pull failure — is
`skills/rollhook-deploys/SKILL.md`'s "Fourth pattern: health-probe 404s during a
rollout". IMAGE_TAG validation rejections and unhealthy-container rollbacks also
live there.

- **Root cause class:** the zot registry (behind Cloudflare) returned a
  transient 502 while the deploy agent's pull raced a concurrent push — the
  manifest GET hit mid-write or an origin blip. The deploy agent marks the
  attempt failed; a retry (RollHook retry or next webhook) usually pulls the
  final manifest digest fine.
- **Diagnosis:** `logs vps rollhook` → the 502ed digest is a different sha
  than the one that later GETs 200; then `containers vps` → the service's
  container was recreated (fresh `startedAt`, `restartCount: 0`) running the
  **alert's image tag** — that's the self-resolve signal.
- **Verb:** none needed once recreated healthy. Verify image tag == alert tag
  and `restartCount: 0`, then close.
- **Escalate only if:** the container stays on the old tag after a retry
  window (~5 min), or the 502 pattern recurs across several deploys (then
  investigate Cloudflare→origin timeouts / zot storage, don't keep re-deploying).

---

## Approval gate — why a read-only command can hang

Incident-response commands can stall waiting on an approval push notification
Johannes may not see (worst at early-morning hours). What's fixed and must
not be re-proposed:

- **`approvals.mode` and `approvals.timeout` are Johannes's settings, not
  ours to change.** Any read or write of `config.yaml` — every spelling,
  symlink target included — is itself denied unconditionally, ahead of the
  smart judge, and cannot be worked around by rephrasing. If a config change
  is genuinely warranted, state the exact YAML and hand it to Johannes; do
  not retry the write.
- **`smart` mode** auto-approves low-risk read-only commands via a guard
  model and fails closed on anything ambiguous — an ambiguous verdict always
  becomes a human prompt, never a silent approval.
- **`command_allowlist` stays empty** and **`cron_mode` stays deny** — do not
  propose widening either; a prior widening attempt (blanket-approving
  `python3 -c` / `perl -e` / `node -e`) was itself the incident.
- **The sanctioned remediation path is `hermes-ops.sh`** (this skill) — its
  fixed verb set with `--why`/`--confirm` is what exists precisely so
  mutating ops don't need ad-hoc approval in the first place. Escalate
  anything the verb set doesn't cover rather than improvising raw
  `ssh`/`docker`/`sqlite3`.
- **Compound commands are refused more often than single-purpose ones** —
  both over SSH and locally: piped commands, loops, and semicolon-joined
  calls are more likely to hit the approval gate than one focused
  read-only call. Keep diagnostic terminal calls to one command with a
  redirect or a status-code probe; process the output in a separate step.

## Git constraint — homelab deploy key is read-only

The homelab's deploy key can `git pull` but never `git push`. A code fix
flow is therefore always: commit on the mini → deploy via the ops `redeploy`
verb (which pulls from origin) → never attempt to push from the homelab
itself.
