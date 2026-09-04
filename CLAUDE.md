# hermes-agent — Hermes Agent Instructions

Commands, tables and gotchas; each section's narrative lives **verbatim** in the `docs/*.md` it
points at — nothing was dropped, only relocated.

## What This Repo Is

VCS source of truth for Johannes's Hermes Agent setup, Mac Mini-only. Everything here is
symlinked into `~/.hermes/` — edit at either end, git sees it here.

Audio (TTS + STT) is the **`audio-gateway`** service (`~/SourceRoot/audio-gateway`), an
OpenAI-compatible VPS container at `https://audio-gateway.jkrumm.com/v1` over the tailnet.
Hermes only points its native `openai` TTS/STT providers at it in `config.yaml` — this repo
installs and patches no audio service, and `make setup` has no `dotfiles` dependency. TTS =
ElevenLabs via the IU Replicate route: `elevenlabs/flash-v2.5` (voice "Mark") for chat replies,
`elevenlabs/v3` for briefings (`skills/briefing-tts`), US-routed; STT = `gpt-4o-transcribe`.
The gateway routes by model id, so the vendor lives in one field (`tts.openai.model`).
Rationale: `modelpick/docs/decisions/audio-stack.md`.

**This repo is public.** Anything Hermes writes here gets read for tailnet names, node IPs,
workspace user ids and `homelab-private` internals before it is committed — all four appeared on
the first pass.

**After any edit: commit here.**

## Symlink Map

`make setup` writes these symlinks:

| File here | Live path | Notes |
|-|-|-|
| `config.yaml` | `~/.hermes/config.yaml` | edit here, live immediately |
| `.env.tpl` | `~/.hermes/.env.tpl` | the one list of `KEY=op://…` refs |
| `SOUL.md` | `~/.hermes/SOUL.md` | |
| `cron/` | `~/.hermes/cron/` | Hermes-driven (LLM) cron jobs |
| `scripts/` | `~/.hermes/scripts/` | cron pre-run scripts (the security check requires they live under `HERMES_HOME/scripts/`) + host-level shell scripts |
| `hooks/` | `~/.hermes/hooks/` | add hooks here |
| `plugins/{name}/` | `~/.hermes/plugins/{name}/` | **`HERMES_PLUGINS` is the source of truth.** Today `dispatch-approval` (the Ed25519 signer). Must **also** be enabled once — `hermes plugins enable <name>` → `plugins.enabled`; the symlink alone is inert. |
| `config/` | `~/.hermes/config/` | tracked agent-facing config — `dispatch-repos.json`: root, `deny`, `defaultTier`, per-repo ceilings |
| `skills/{name}/` | `~/.hermes/skills/{name}/` | **`HERMES_SKILLS` in the Makefile is the source of truth** — 17 dirs: `capture argo-api work karakeep obsidian reading wildrift research-gateway image-delivery homelab-ops homelab hermes-gateway briefing-tts claude-dispatch rollhook-deploys hyperdx podcast`. `homelab` is also a **category dir**: `skills/homelab/{tailscale-diagnostics,torrent-stack-diagnostics}/` load as their own skills through the parent symlink, no `HERMES_SKILLS` entry. |
| `USER.md` | `~/.hermes/memories/USER.md` | **copied** — Hermes writes to it |

**A skill is durable only if symlinked from this repo.** `config.yaml`'s
`skills.external_dirs: [~/SourceRoot/hermes-agent/skills]` satisfies the v0.16.0+ skill-trust
check **and** makes the background self-improvement curator refuse every mutating action on it;
a skill created ad hoc under `~/.hermes/skills/` has neither protection and gets silently
rewritten by accretion. Detection is automatic — `watchdog-poll.py`'s `stray_skill` source (30
min, weekly reminder) flags a non-symlink dir with its own `SKILL.md` absent from
`.bundled_manifest` **and** locally mutated per `.usage.json` (`created_by == "agent"` or
`patch_count >= 1`). Adoption, manual fallback, why that predicate:
**`docs/skill-durability.md`**; the original table notes + per-script detail:
**`docs/symlinks-and-agents.md`**.

**Host-level scripts** (user LaunchAgents, not symlinked):

| `scripts/…` | Agent `com.jkrumm.…` | Cadence | What it does / asserts before its Kuma push |
|-|-|-|-|
| `hermes-liveness.sh` | `hermes-liveness` | 300s | gateway state + Slack `connected` + rendered-ref count ≥ `KEY=` count in `.env.tpl` → `$UPTIME_PUSH_HERMES` |
| `hermes-backup.sh` | `hermes-backup` | daily 03:00 | rsync `~/.hermes/` → `homelab:/mnt/hdd/backups/hermes/`; `mkdir`-lock (`~/Library/Caches/hermes-backup.lock`) so two runs never race `rsync --delete` → `$UPTIME_PUSH_BACKUP` |
| `hermes-webui-launch.sh` | `hermes-webui` | KeepAlive/30s | resolves the password, execs the clone's `start.sh --foreground` |
| `hermes-webui-liveness.sh` | `hermes-webui-liveness` | 5 min | `/health` → 200 **and** unauth `/` → non-2xx → `op://hermes/uptime-kuma/webui-push-url` |
| `hermes-serve-launch.sh` | `hermes-serve` | KeepAlive/30s | counts the `serve.env.tpl` refs, refuses below the full set, execs `hermes serve --host 127.0.0.1 --port 9119 --skip-build` |
| `hermes-serve-liveness.sh` | `hermes-serve-liveness` | 5 min | `/api/status` → `auth_required: true` → `op://hermes/uptime-kuma/serve-push-url` |

Templates live in `launchd/`, rendered into `~/Library/LaunchAgents` by `make setup` (`_agents`
→ `_render-plists`, `__HOME__` substituted; unchanged content is a no-op, so a re-run never
bounces a healthy agent). `HERMES_PLISTS_RETIRED` unloads + removes labels this repo no longer
installs, so a rename can't leave two agents racing a port. Logs:
`~/Library/Logs/hermes-*.{log,err}`, declared in `dotfiles/scripts/log-rotate.sh` — never
globbed, so an unregistered log is an unbounded one.

**Scheduled jobs are LaunchAgents, never macOS crontab** — a `crontab -` *write* needs Full
Disk Access and hangs forever on the headless mini, which is what made `make setup` a
human-at-the-screen target. Removing legacy lines is itself such a write, so it lives behind
the one-time `make cron-migrate` (`timeout 15`-bounded, needs a Full-Disk-Access terminal).
Done 2026-08-02 — no hermes entries in `crontab -l`. Reasoning: **`docs/scheduled-jobs.md`**.

**Claude Code per-repo skills** (`.claude/skills/`, committed, no symlink): `/hermes-validate`
(test routing, fix SOUL.md / SKILL.md) · `/hermes-update` (pull upstream, re-apply patches,
restart gateway).

## Dispatch Bridge — handing repo work to Claude Code

Hermes observes well and reads repos badly — `gpt-5.6-luna` with a `terminal` tool cannot use a
repo's `CLAUDE.md`, `.claude/rules/` or `.claude/skills/`. `scripts/hermes-cc.sh` is the bounded
client that hands the episode to Claude Code (sideclaw's `dispatch` job tool) instead. Design:
**`docs/dispatch-bridge.md`**; why each bound is shaped this way, and the incidents that forced
them: **`docs/dispatch-bridge-decisions.md`**.

**Verbs:** `dispatch <repo>` · `status <job-id>` · `list [open|today|all]` · `merge <job-id>` ·
`cancel <job-id>` — `cancel` abandons the LOCAL record only (sideclaw has no cancel endpoint,
and the help text says so).

| Invariant | Detail |
|-|-|
| No verb takes a path, command or URL | a dispatch names a **repo** — a bare single-segment name resolved under the single `root` in `config/dispatch-repos.json`. `.`/`..`/dotted names refused; the resolved checkout's parent must **be** the resolved root. Regression-tested. |
| `deny` list | `dotfiles-private`, `homelab-private`, `brain` — stay there. |
| Brief is data, never argv | stdin (`<<'BRIEF'` quoted heredoc) or `--brief-file`. **No `--brief`, deliberately** — as argv it would be shell-expanded before the script ran. |
| Tiers | `investigate` (read-only → verdict) · `author` (+ one GitHub issue) · `implement` (`dispatch/…` branch + **draft** PR). **Every tier runs in its own throwaway worktree**, read tiers included — `readOnly` removes Edit/Write, not Bash. |
| Ceilings | `defaultTier: implement`, `investigate` floor for `dotfiles`/`vps`/`homelab`. A tier above a repo's ceiling is **refused, exit 4**, never downgraded. No `implement` allowlist, deliberately. |
| `implement` gate | `--why` **and** `--confirm`. Without `--confirm` it prints the plan + a `wouldNeverDo` list and exits **0** — printing the plan *is* the successful outcome. `--why` is the audit record. |
| Secret scan | the handler **refuses** (never redacts) a brief carrying credentials, and scans the **diff's added lines** too — handler-side, not the target repo's `pre-commit` hook. |
| Budgets (`--max-budget-usd` is API-only, can't cap a Max session) | 20 dispatches/UTC day, ≤5 `implement`, ≤3 `merge`, 240s `--wait` cap. Every reporting path returns a `budget` object + a `warning` near a ceiling. Raising one is Johannes's call — `HERMES_CC_{DAILY,IMPLEMENT,MERGE}_BUDGET`, and `claude-dispatch` forbids the agent setting them. |

**`--confirm` is an approval artifact, not an instruction.** The plan posts Approve/Deny buttons
into the origin channel; the click lands in the gateway, which signs it with an **Ed25519 key
minted at startup, held in RAM only** (`plugins/dispatch-approval/`, public half at
`~/.hermes/dispatch-approval.pub`). Only the signature is consulted — every `dispatch_approvals`
column is writable by this uid. Bound to `verb|repo|tier|payload|why`, single-use, 30-min TTL,
**fails closed** on no plugin / no key / no gateway / expired / spent / hash mismatch; a gateway
restart voids pending approvals. Enable once: `hermes plugins enable dispatch-approval`.
*Tell for the one bug this has had:* a refusal saying **"has not been clicked yet"** despite a
visible Approve → `grep 'published public key'` vs `Wired 2 plugin action handler` in
`~/.hermes/logs/agent.log`; a publish with no matching wire line means a non-gateway process
overwrote the public key.

**`merge <job-id>` lands the draft PR with no human on GitHub** (owner decision). Takes a **job
id, never a PR number or URL** — the PR comes from the `dispatches` row. Eligibility is
**derived**: a repo in `dotfiles/config/pr-required-repos.json` can never be auto-merged. Every
implement-time bound is re-checked against the **current** head (base = default branch, head = a
`dispatch/…` branch in this repo never a fork, no `.github/workflows|actions` path, sideclaw's
40-file/2000-line ceilings, `mergeable_state` exactly `clean` — `blocked`/`unstable` are
refusals) and the call **pins the head SHA**. Deliberately **not** gated on the signed approval.
The GitHub credential goes in as a curl config on **stdin, never argv**.

**Audit log** `~/Library/Logs/hermes-cc.log` — one line per invocation, refusals included, with
five load-bearing modes: `opened` · `planned` · `dry-run` · `refused` · `merged`. Register it in
`dotfiles/scripts/log-rotate.sh`'s `FILES` array.

**`dispatches` table** in `~/.hermes/watchdog.db` (additive DDL; `events` untouched).
`reported_at IS NULL` = the sweeper still owes a message; a `--wait` returning a terminal verdict
stamps it, `status` deliberately does not, and a dispatch with no `origin_channel` closes with
the sentinel `undeliverable:no-origin-channel`. `artifact_url` + `merged_at` are denormalized
columns added by an `ALTER TABLE` on every connect in **both** settlers (`hermes-cc.sh`'s
`sync_record`, `dispatch-sweep.py`) — `CREATE TABLE IF NOT EXISTS` no-ops on an existing table.

**`slack.allow_bots: all` is deliberate — do not "fix" it.** The trust boundary is the
workspace, not human-vs-bot: HomeLab/VPS/Argo post from inside the tailnet and live auto-triage
of an alert in `#alerts` depends on it. The real exposure is hostile *content* relayed by a
trusted sender — hence `watchdog-poll.py` and `briefing-coverage.py` marking non-`jkrumm` GitHub
items as third-party instead of authenticating the messenger.

**GitHub credential `op://mini/github/token` needs three grants** — `Contents: write` (push)
**plus** `Issues: write` and `Pull requests: write` (the artifact). With only the first, the
branch pushes and the last step fails as "Resource not accessible by personal access token".
sideclaw's `gho_` `GITHUB_TOKEN` fallback must not quietly become the real dependency.

**Tests** (`~/.hermes/hermes-agent/venv/bin/python3`): `test_hermes_cc.py` (130, stubbed job
server + GitHub), `test_dispatch_approval.py`, `test_raw_agent_guard.py`,
`test_repo_write_guard.py`, `test_dispatch_sweep.py`. The other half is `sideclaw/tests/`
(`bun test`, 175, mutation-verified) — worktree isolation, the diff-refusal ladder, the
added-lines secret scan, the nonce fence around the brief.

**Hermes cron pre-run scripts** (run by `hermes-agent` before each run, not launchd):

| Script | Does |
|-|-|
| `briefing-context.py` | `briefing-state.json` → `BRIEFING_CITY` + `BRIEFING_SUPPRESSED`; calls `briefing-coverage.py`; output lands as `## Script Output` |
| `briefing-coverage.py` | TickTick backlog + open GitHub items → `COVERAGE_AVAILABLE`, `TICKTICK_BACKLOG`, `TICKTICK_HIGH_PRIO_DATELESS`, `GITHUB_OPEN_BY_REPO`, `GITHUB_FRESH_48H`, `GITHUB_TOTAL`. Key from the process env, else `secrets-run read op://common/api/SECRET` |
| `watchdog-poll.py` | UptimeKuma, Docker (homelab + vps), GitHub, Slack `#alerts`, 1Password ref health on both servers (a no-op `op run … -- true` over ssh — one dangling ref takes a whole shared template's crons down), stray skills; reconciles `~/.hermes/watchdog.db`; emits `NEW=`/`REMINDERS=`/`RESOLVED=` |
| `watchdog-slack.py` | `no_agent` cron, 30 min — wraps `watchdog-poll.py --slack-body`, pings `$UPTIME_PUSH_WATCHDOG` on a clean run |
| `watchdog-summary.py` | read-only snapshot for the morning briefing; projects `DISPATCHES_OPEN`/`DISPATCHES_RECENT` (~18h), silent when idle |
| `dispatch-sweep.py` | `no_agent` cron, 5 min (registered via `hermes cron`, **not** `make setup`) — polls `localhost:7705/api/jobs/:id`, folds terminal jobs into the row, delivers the verdict via `hermes send`, stamps `reported_at` only on exit 0. `--dry-run` touches no row |
| `briefing-state.json`, `skills/capture/state.json` | *gitignored* runtime state, seeded from `*.example.json` |

- **Quiet hours (00:00–07:00) and vacation defer a notification, they do not burn it.**
  `_run_poll`/`reconcile`/`upsert_grouped` take `deliver`: rows still insert, refresh and
  resolve under suppression, only `notified_at`/`last_reminder_at` is withheld, and
  `upsert_grouped` re-opens a resolved signature on recurrence
  (`test_watchdog_delivery.py`, 24 checks). **Grouped sources** (`slack_alert`, `slack_update`,
  `hermes_log`) are append-only, auto-resolving after 7 idle days (`GROUPED_TTL_DAYS`); state
  sources resolve by disappearance through `reconcile()`.
- **At-least-once for the verdict, at-most-once for the nudge.** A verdict posts as Hermes's own
  bot user, which Slack ingest drops — so a `done` + `implement` + `artifactUrl` + unmerged
  dispatch also gets a nudge via argo's Slack API (posting as the HomeLab bot, which Hermes *does*
  ingest). **The nudge carries only bridge-owned fields** (job id, repo, tier, artifact URL),
  never episode prose — a sentinel test asserts it. A `merged_at` row rewrites the
  header/artifact/next line, so it never says "review this draft PR" for a merged one.
- **`hermes cron create --script` rejects any substantial script** — `cron/lifecycle_guard.py`
  fails closed on an exhausted recursion budget, so a long file (or one whose comments quote
  command lines) is refused as *"contains a gateway lifecycle command"* regardless of content.
  Keep entry points thin, logic in an imported module (`dispatch-sweep-cron.py` →
  `dispatch-sweep.py`); verify with `contains_gateway_lifecycle_command_or_referenced_script`.

Detail: **`docs/watchdog.md`** · **`docs/scheduled-jobs.md`**.

## Secrets — native `secrets.command` over the headless cache (v0.19.0+)

No plaintext `~/.hermes/.env`, no launch wrapper. `config.yaml`:

```yaml
secrets:
  command:
    enabled: true
    command: "$HOME/.local/bin/secrets-run export --env-file=$HOME/.hermes/.env.tpl | sed 's/^export //'"
    helper_timeout_seconds: 15
    override_existing: true
```

`secrets-run` is the dotfiles shim over the age-encrypted offline cache; `.env.tpl` stays the
single list of `KEY=op://vault/item/field` refs. The `sed` exists because `export` emits
`export K='V'` while the bulk parser wants `K=V`. 0.29s for 27 refs (default budget 3s), and
secrets resolve for **every** hermes invocation — gateway, CLI, cron.

- **Not `secrets.onepassword`**: it needs an interactive `op` session (hangs headless) or a
  standing `OP_SERVICE_ACCOUNT_TOKEN` (a live credential on an always-on box). The sealed cache
  is strictly stronger — its contents are the explicit `dotfiles-private/headless.refs` allowlist.
- **Fail-soft, monitored.** The `command` source can't abort startup; it degrades to "no secrets
  applied" + a warning. `hermes-liveness.sh` covers both halves — total failure via
  `platforms.slack.state == "connected"`, partial via `KEY=` count vs rendered count, retried
  once after 2s (288 decrypts/day; one transient failure must not page), `timeout`-bounded.
- Manual check: `Command helper: applied 27 secrets` in `hermes gateway status`, `✓ secrets (27
  refs …)` from `make status`.
- **launchd works** — `ai.hermes.gateway` is genuinely supervised. The plist is stock
  (`venv/bin/python -m hermes_cli.main gateway run --replace`), so `hermes gateway install` is a
  no-op; its `Bootstrap failed: 5` output is noise — check `gateway status`.

Rationale + what this replaced: **`docs/secrets-command.md`**.

## Hermes WebUI (browser UI, tailnet-only)

Third-party (`github.com/nesquena/hermes-webui`, cloned at `~/SourceRoot/hermes-webui`), reads
`~/.hermes` directly, used from the iPhone. **The clone stays upstream's tree** — every local
decision lives here, so it can be deleted and re-cloned. It runs inside the **gateway's own
venv** (`HERMES_WEBUI_PYTHON`; only deps are `pyyaml` + `cryptography`), so a WebUI dep bump
lands in the venv the gateway runs from.

| Piece | Where |
|-|-|
| Launcher (env + secret resolution) | `scripts/hermes-webui-launch.sh` |
| Service / heartbeat definitions | `launchd/com.jkrumm.hermes-webui{,-liveness}.plist.template` |
| Tailnet ingress, phone | `dotfiles-private/tailscale-serve.mini.conf` (`:8789`) + ACL `tag:phone → tag:mac tcp:8789` |
| Tailnet ingress, Macs | `dotfiles/config/Caddyfile` → `hermes-web.test` ⇒ `https://hermes-web.mini.jkrumm.com` |
| Password | `op://mini/hermes-webui/password` |
| Monitor | homelab `uptime-kuma/monitors.yaml` → `Hermes WebUI - Push` |

- **Two doors, both stay** — `:8789` (`tailscale serve`) is the **phone's**, the Caddy clean door
  the **MacBook's**. ACL-forced: the serve grant is `tag:phone → tag:mac` and **both Macs are
  `tag:mac`**, so widening it would expose the *work* laptop to every session, memory and log;
  the clean door is `tag:devhost`, mini-only. **Never bind 8789 on the tailnet interface in
  Caddy** — it collides head-on with the serve row.
- **The clone's `.env` must not exist, and `make status` asserts it** — `start.sh` sources it
  with `set -a` *after* the launcher's env, so a stale file silently overrides everything,
  password included.
- **The launcher resolves the whole `.env.tpl`**, not just the password: the WebUI runs its own
  in-process agent, but `server.py` is not `hermes_cli.main`, so `${OPENAI_BASE_URL}` + 25
  siblings reach httpx unexpanded. Symptom names nothing — *"Error: Connection error."*, log
  `base_url=${OPENAI_BASE_URL} … UnsupportedProtocol`, gateway healthy throughout.
- **No credential fallback** — an unresolvable ref exits 78 and the service stays down, safer
  than serving on a credential nobody can rotate. **The heartbeat asserts auth, not liveness**:
  `/health` answers before the password middleware is wired, so an empty-password WebUI would
  otherwise look green.

Narrative, incl. what the unattended build got right and wrong: **`docs/hermes-webui.md`**.

## `hermes serve` — the backend Hermes Desktop connects to

Upstream's desktop client (`hermes desktop`, Electron, `apps/desktop/`) cannot use the
OpenAI-compatible API on `:8642` — it speaks to `hermes serve`, a JSON-RPC/WebSocket backend on
**`:9119`** whose load-bearing routes are `GET /api/status` (auth discovery) and `WS /api/ws`.
`:8642` has no `/api/ws` at all — which is why argo's dashboard chat can use it and Desktop
cannot. `hermes dashboard` is the same server with a browser UI. **A separate process from the
gateway, and upstream expects both** — Slack does not move to it.

| Piece | Where |
|-|-|
| Launcher | `scripts/hermes-serve-launch.sh` |
| Service + heartbeat | `launchd/com.jkrumm.hermes-serve{,-liveness}.plist.template` |
| Auth refs | `serve.env.tpl` → `op://mini/hermes-serve/{username,password,session-secret}` |
| Door | `dotfiles/config/Caddyfile` → `hermes-api.test` ⇒ `https://hermes-api.mini.jkrumm.com` |
| Monitor | homelab → `Hermes Serve - Push` |

- **Client side:** *Settings → Gateways → Add connection → Remote gateway*, persisted to
  Electron `userData/connection.json` (`mode: local|remote|cloud|ssh`).
  `HERMES_DESKTOP_REMOTE_URL` / `_TOKEN` are an app-wide override, not the normal route (URL
  without token is a hard error). **In remote mode the mini is the execution boundary** — every
  tool runs there, so Desktop-on-MacBook browses the *mini's* filesystem.
- **`serve.env.tpl` is deliberately NOT `.env.tpl`.** `secrets-run` fails **atomically**, so an
  unsealed ref in `.env.tpl` renders **zero** secrets and brings the *gateway* up
  credential-less at its next restart (suppressing its heartbeat too). A second template scopes
  that blast radius to serve alone.
- **An unset `${VAR}` in config.yaml expands to the literal `${VAR}`, which is truthy**
  (`_expand_env_vars`) — an unresolved serve would authenticate on the password
  `${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD}`. Hence the launcher **counts** rendered refs and
  refuses below the full set; `make status` reports the same count.
- **Auth engages despite the loopback bind**, via the operator-declared `dashboard.public_url`
  clause. **Do not add a second auth layer in Caddy** — it breaks Desktop's `/api/status`
  discovery handshake. `--insecure` is a documented no-op since the June 2026 hardening. The
  heartbeat asserts `auth_required`, not liveness — `/api/status` is public by design.
- **Three front-ends share one `~/.hermes` and one `state.db`** (gateway, WebUI's in-process
  agent, `serve`). If sessions vanish/interleave/lock, suspect this first; `hermes serve
  --isolated` is the escape. Detail: **`docs/hermes-serve.md`**.

## Gateway HTTP Exposure (argo dashboard chat)

The gateway runs an OpenAI-compatible HTTP API alongside Slack so the **argo VPS dashboard
chat** can reach Hermes. Four env vars (framework keys in `hermes_cli/config.py`), resolved at
startup from `.env.tpl` via `secrets.command`:

| Var | Value |
|-|-|
| `API_SERVER_ENABLED` / `API_SERVER_PORT` | `true` / `8642` — literals |
| `API_SERVER_HOST` | the mini's Tailscale IP — **tailnet-only bind**, no LAN listener. `op://hermes/gateway/host` (never a literal in git) |
| `API_SERVER_KEY` | bearer gating **every** request, even loopback. `op://hermes/gateway/api-server-key` |

**Shared secret:** `API_SERVER_KEY` **must equal** argo's `HERMES_API_KEY` — canonical
`op://hermes/gateway/api-server-key`, mirrored to `op://vps/argo/HERMES_API_KEY`. Rotate both op
items, then `ssh vps "cd ~/vps && ENV=prod make argo-env && ENV=prod make argo-up"`; **no gateway
restart** — only argo redeploys. Mismatch = **401**; connection-refused = not bound to the
tailnet IP. Argo holds `HERMES_BASE_URL=http://<mac-tailnet-ip>:8642/v1`; ACL grants
`tag:vps → tag:mac` on `tcp:8642`.

**Verify from the VPS** (URL+key from `apps/argo/.env`): `curl .../health` → 200 unauth ·
`curl -H "Authorization: Bearer $KEY" .../v1/models` → 200 · a real
`POST .../v1/chat/completions` completes · `lsof -nP -iTCP:8642 -sTCP:LISTEN` shows the tailnet
IP, not `127.0.0.1`. **`docs/gateway-http-api.md`**.

## Homelab API Integration

`skills/argo-api/SKILL.md` endpoint tables are regenerated from
`https://argo.jkrumm.com/api/openapi/json` by the homelab `/docs` skill. The spec's **14 tags**
split three ways: **personal** (`argo-api`) — Garmin Health, Strength, WalkingPad, Productivity,
Infrastructure, External Data, Reading, Usage Tracking, System; **work** (`work` skill) — M365,
Atlassian, GitLab; **not agent-facing** — Hermes Chat (`/hermes/*`) + AI Gateway (`/ai/v1/*`).
`/reading/*` is the standalone `reading` skill. **API secret:** `op://common/api/SECRET`
(account `tkrumm`), in `.env.tpl`.

- **`work` skill = read-only across M365 / Confluence / GitLab, with one write exception:
  Jira** — create/update/transition/comment on Johannes's own tickets (argo auto-stamps
  Team=Prometheus, no agent attribution). Never sends Teams messages, posts mail, creates
  Confluence pages, opens MRs or speaks for teammates. `/m365/team` is the cross-system identity
  hub; MRs auto-extract `jiraKeys`.
- **Briefings carry exactly three work signals**: today's Outlook calendar (merged with personal
  under `:office:`), Jira sprint commitments, GitLab MRs needing action; the evening report keeps
  only tomorrow's merged calendar. **Everything else is ad-hoc only** — `/m365/important`, chats,
  Confluence, GitLab events/commits, WalkingPad, `/usage/*` — never in briefings, never in the
  watchdog (personal apps + infra alerts only).
- **Errors:** `503 M365 not authenticated …` → `bun m365:auth:prod` in `~/SourceRoot/argo`;
  `503` on `/gitlab/*` or `/atlassian/*` → PAT expired.
- **garmin-health vs strength:** Garmin = passive measurement (`/daily-metrics`, `/recovery`,
  `/training-load`, `/fitness-direction`, `/activities`, `/weight-log`, `/user-profile`);
  Strength = active lifting (`/workouts`, `/workout-sets`, `/exercises`) + the 13-endpoint
  `/workouts/summary/*` suite. Bridge: `/workouts/summary/readiness`, in `strength`.

Detail: **`docs/argo-surface.md`**.

## Research (research-gateway)

Deep cited research is the standalone **research-gateway** (`research.jkrumm.com`, VPS,
**Tailscale-only**), used through `skills/research-gateway/SKILL.md` via `terminal`:
`POST /research/ {query, depth?}` → `{jobId}`, poll `GET /research/{jobId}` until `status: done`
→ `{result: {report, citations[], sources[]}}`. Async because even `quick` runs 1–3 min.
**Preferred path for substantive / factual / library-version questions** over built-in Tavily
search, which stays for quick lookups. EU/IU models, off Max.

- **Auth:** `RESEARCH_API_KEY` = `op://vps/research-gateway/API_SECRET` (shared with the Claude
  Code `/research` skill), in `.env.tpl`; base URL hardcoded in the skill, like argo/karakeep.
- **Routing (SOUL.md):** "research X now" → `research-gateway`; "remind me to research X later"
  → `capture` → TickTick; book/novel discovery → `reading`.
- **Named `research-gateway`, not `research`** — upstream's bundled skill *category* dir
  `~/.hermes/skills/research/` would collide with a top-level `research` symlink. Routing is by
  description/tags, so "recherchier mal" still triggers it.
- Its host is in both allowlist patches. Detail: **`docs/research-gateway.md`**.

## Observability triage (hyperdx)

`skills/hyperdx/SKILL.md` gives Hermes an authenticated path into ClickHouse instead of a browser
login wall. HyperDX/ClickStack is **VPS-only** (`hyperdx.jkrumm.com`, Tailscale-only), exposing a
stateless JSON-RPC/SSE MCP server at `/api/mcp` — the same server sideclaw's `otel` tool uses,
same credential. The skill carries one verified curl template (`tools/call` → `clickstack_sql`,
SSE parsed `grep '^data:' | sed 's/^data: //' | jq`) against `default.otel_traces` / `otel_logs` /
`otel_metrics_*`, plus the SQL behind each of the three live alerts
(`vps/observability/alerts/*.json`), so a triage re-runs the condition that fired.

- `HYPERDX_AGENT_ACCESS_KEY` in `.env.tpl` ← `op://vps/clickstack/AGENT_ACCESS_KEY` (`make
  hyperdx-agent-setup` in `vps`, cached in `headless.refs`).
- **Escalation reuses the dispatch bridge**: `--tier author` to file an issue, `--tier
  implement` only after confirmation. Exception — a root cause inside Traefik/ClickStack config
  is scoped to `vps` (`investigate`-only), so the skill falls back to `capture` → `gh issue
  create`.
- **No ClickHouse HTTP (8123) on the tailnet** — `vps/compose.monitoring.yml` publishes only
  `:13133` (collector health); querying goes via HyperDX's MCP/REST. **HomeLab has no parallel
  stack** — the VPS is the sole instance, HomeLab only monitors it via UptimeKuma.
- Its host is in both allowlist patches (see *Local Modifications*).

The triage gap that motivated it: **`docs/hyperdx-triage.md`**.

## Podcast generation (podcast)

`skills/podcast/SKILL.md` turns notes into a long-form two-host German episode via a **job API on
the audio-gateway** (same VPS/tailnet service as TTS/STT) and publishes the MP3 (chapters + cover)
into Audiobookshelf. Submit-and-poll like `research-gateway`, **not** a single
`/v1/audio/speech` call like `briefing-tts`.

**No secret** — tailnet-gated, caller identified by the bearer label `hermes`
(`Authorization: Bearer hermes` + `x-audio-source: hermes`), the same literal
`tts.openai.api_key`/`stt.openai.api_key` use; nothing new in `.env.tpl`. SOUL.md's TTS rule 4
("NEVER curl an audio endpoint") exempts `/v1/podcasts*` — there is no native tool for this
pipeline. `audio-gateway.jkrumm.com` is in both allowlist patches.

## Second Brain (Obsidian + KaraKeep)

Two skills, deliberately distinct roles — don't blur them:

- **`obsidian`** — the **source of truth**: read/search/write the PARA vault at
  `~/SourceRoot/brain/`, also a git repo shared with Claude Code (`/brain`). A LaunchAgent
  pulls+pushes every 5 min; **on this mini it never auto-commits, so a write isn't durable until
  committed**. **CLI-first** (`obsidian-cli` through the running app's API), filesystem fallback
  when Obsidian is down. No secret. Two layers, validated by `node .scripts/vault-lint.mjs`:
  strict atomic English concept notes in `wiki/` (`type`+`description`), light curated
  `Projects`/`Areas` linking *down* into it; no `Resources` tier. Contract:
  `~/SourceRoot/brain/AGENTS.md`.
- **`karakeep`** — the **read-later bucket**: REST on `https://karakeep.jkrumm.com/api/v1`
  (Bearer `$KARAKEEP_API_KEY` ← `op://hermes/karakeep/api-key`, Tailscale-only). Links/text,
  full-text search (Meili — no semantic search in 0.32.0), lists incl. smart, tags, highlights;
  AI auto-tagging async. `skills/karakeep/state.json` (gitignored, seeded by `make setup`) caches
  lists+tags, refresh-on-miss.

**Routing** (`capture` is the router): KaraKeep = reference/reading you consume · Obsidian =
durable knowledge you author · TickTick = human action · GitHub = code change.

**Bundled-skill collision:** upstream's stock `obsidian` skill was removed from
`~/.hermes/skills/note-taking/obsidian/` so ours is canonical, and it **re-seeds on `hermes
update`** — `/hermes-update` carries the `rm -rf` step. Kobo/Readeck plan + detail:
**`docs/second-brain.md`**.

## Wild Rift (champion pool tracker)

`skills/wildrift/SKILL.md` maintains the four-champion pool — Thresh, Pyke (support), Rammus,
Hecarim (jungle). **Vault-first:** builds, runes, matchups, bans and a dated stats snapshot live
at `~/SourceRoot/brain/Areas/Gaming/Wild Rift/*.md` (curated surface, not `wiki/`); the open web
via `research-gateway` only *refreshes* a note when a patch moved. No secret, no external API.
Writes use the `obsidian` CLI-first contract and the `git -C ~/SourceRoot/brain …` exemption
(never push — the LaunchAgent syncs).

- **Never a build site directly** — no Riot/Tencent/build-site host is in tirith's
  `_ALLOWED_PIPELINE_HOSTS` or the cron scanner's `_trusted_api_suffixes`, so every fetch routes
  through `research-gateway`.
- **Stats are China-server only** (Riot publishes no Wild Rift API) and swing hard by rank tier
  (0-4 — Hecarim ~45% WR at tier 0 vs ~53.7% at tier 4): **qualify every answer by rank**.
- An Argo `/wildrift/*` group is **built but not deployed**; the skill tells the agent not to
  call it. Detail: **`docs/wildrift.md`**.

## Local Modifications to Upstream

Re-apply after `hermes update`: **one `.patch` file per patched upstream file**, each with `git
apply --3way` (`/hermes-update` carries the loop). `ls patches/` is the count, `make patch-check`
proves they are applied — deliberately not restated here (it drifted at four of the last five
updates). All are regenerated against the current baseline (**v0.21.0**, upstream
`b6f42c667a`), so only a structural rewrite of a touched function needs hand-resolving.

| Upstream file | `patches/…` | What it does |
|-|-|-|
| `tools/tts_tool.py` | `tts-tool-audio-title` | name saved audio from the gateway's `X-Audio-Title` header instead of `tts_<timestamp>.mp3` (also `tts_reply_<uuid>` auto voice replies) |
| `gateway/run.py` | `gateway-auto-tts-voice-only` | auto-TTS answers **voice input only** (`and is_voice_input` in `_should_send_voice_reply`'s fallback), so alerts stop coming back as MP3s. `/voice all` per chat still speaks everything |
| `hermes_cli/web_server.py` | `serve-speak-summary` | Desktop relay read-aloud: a first frame carrying whole text + `done` and ≥ `voice.speak_summary_min_chars` (config **120**, 0 = off) is summarised in one gateway call. `openai` streamer only; needs `voice.client_direct: false` |
| `plugins/platforms/slack/adapter.py` | `slack-cannot-reply-to-message` | `format_message()` pre-steps (`*` → `-`, strip backticks round emoji shortcodes) + `send()` retry: on `cannot_reply_to_message`, drop `thread_ts` and retry flat |
| `gateway/platforms/base.py` | `slack-media-inline-reply-anchor` | pass the text reply's anchor to `send_voice`/`send_video`/`send_document`. **Dormant** under `reply_in_thread: true`, kept applied |
| `run_agent.py` | `run-agent-third-party-endpoint-token-refresh` | broaden `_try_refresh_anthropic_client_credentials`'s skip from Azure-only to every third-party Anthropic-compatible endpoint (stops `~/.claude/.credentials.json` OAuth replacing the IU key). **Dormant**, kept applied |
| `tools/tirith_security.py` | `tirith-hermes-guards` | four guard rules, below |
| `tools/cronjob_tools.py` | `cronjob-tools-allowlist-argo-bearer` | argo/karakeep/research/hyperdx/audio-gateway bearer allowlist in the shared `_strip_cron_safe_constructs`, so a legitimate bearer curl in a cron prompt stops tripping `exfil_curl_auth_header`. GitHub's exempt shape is `Authorization: token $VAR`, **not** `Bearer` |
| `hermes_cli/runtime_provider.py` | `runtime-provider-iu-responses-api` | route the IU `…/openai/v1` leg onto `codex_responses` in `_detect_api_mode_for_url` — **the only way to run a reasoning effort here** |
| `agent/transports/chat_completions.py` | `transport-iu-reasoning-effort` | drop `reasoning_effort` on a gpt-5.x request carrying function tools; clamp `xhigh`/`max` → `high` for the Anthropic fallback |

Re-apply shape:
`cd ~/.hermes/hermes-agent && git apply ~/SourceRoot/hermes-agent/patches/<name>.patch`.
**Anything touching `tirith_security.py`, `cronjob_tools.py` or `runtime_provider.py` needs a
gateway restart** (`launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway`) — modules are
imported once at startup, so a green in-process test says nothing about the running process.
`serve-speak-summary` kickstarts `com.jkrumm.hermes-serve` instead.

**The four guard rules in `tirith-hermes-guards.patch`**, each with its own suite (run with
`~/.hermes/hermes-agent/venv/bin/python3`):

- **trusted-pipeline allowlist** — an `allow` early-return so tirith's `[HIGH] Pipe to
  interpreter` stops firing on `curl https://<trusted>/… | jq/python3`. Hosts: `argo`,
  `karakeep`, `research`, `hyperdx`, `audio-gateway`.jkrumm.com **only** + a safe program set;
  any redirect, `$(...)`, backtick, `;`, `&&`, `||`, `&`, `(`, `>` defers to tirith.
- **`download_then_execute`** — blocks the two-step form of `curl | sh` that upstream tirith
  allows (`curl -o /tmp/f … && sh /tmp/f`, `wget -qO`, `chmod +x`, `$(cat …)`, `<(curl …)`;
  taint follows one `cp`/`mv`/`install` hop). Sits **before** the circuit breaker and the
  allowlist, so it holds when tirith is unavailable (`tirith_fail_open` defaults **True**).
  `test_download_guard.py`: 20/20 blocked, 27/27 allowed.
- **`raw_agent_invocation`** — blocks Hermes composing its own `claude` / `claude_iu` /
  `claude_bridge` / `ca` / `opencode` call instead of using the dispatcher (`claude_bridge`,
  `opencode`, `mosh` stay in the denylist as defense in depth although retired on this machine).
  Follows `timeout`/`env`/`nohup`/`sudo`/`xargs`/`nice` wrappers, `K=$(...)` prefixes, `sh -c`,
  subshells. `test_raw_agent_guard.py`: 31 blocked, 24 allowed.
- **`raw_repo_write`** — blocks Hermes editing a repo itself instead of dispatching.
  **Unconditional, not path-scoped**: a `git commit` names no path, so a path rule is evaded by
  `cd`. Denylist of git write verbs + mutating `gh`/`api.github.com` calls; inspection verbs
  untouched. **Two exemptions:** `gh issue create` + the `/issues` API path, and the brain vault
  **when the command names it** (`git -C ~/SourceRoot/brain …`, or a `cd` to it on the same
  line) — a bare `git commit` stays blocked. `test_repo_write_guard.py`: 67/67 blocked, 55/55
  allowed.

**The one bypass that actually happened: a newline.** `_agent_segments` (shared by the two
agent/repo guards) ran `shlex` with `whitespace_split=True`, whose whitespace set contains `\n`,
so a multi-line block welded into one argv and nothing past line 1 was scanned. Fixed by moving
`\n`/`\r` into `punctuation_chars` (splits **outside quotes only**). **A shared helper needs
shared tests.** Deliberate residual limits: cross-call download-then-execute, value indirection
(`G=git; $G push`), `xargs` execution, decode chains.

**Slack threading is a context-window boundary.** `slack.reply_in_thread: true` makes
`build_session_key()` append `thread_ts` whenever `source.thread_id` is set, so **one thread ==
one session == one context window**. Continue a topic *inside* its thread; a new top-level
message is deliberately a clean slate. `session_reset.mode` is unset, so only the compressor
bounds a long thread.

Per-file detail, every retired patch and why, the v0.18.x platform rewrite: **`docs/patches.md`**.
Guard rationale + incident record: **`docs/guards.md`**.

## Model, context window and reasoning effort

Numbers are **probed against the live IU endpoint**, not read off a model card — every
published source disagrees in some direction. Re-probe after an endpoint change.

| | Value | How established |
|-|-|-|
| Input cap, `gpt-5.6-luna` | **922,000** | 900k ok; 1.1M → `context_length_exceeded` "configured limit of 922000 tokens" (a *combined* input+reasoning+output budget) |
| `/v1/models` metadata | `ContextSize: "105000"` | **Wrong** — 110k/260k/520k/900k all succeed. Never configure from it |
| Published model card | 1,050,000 in / 128,000 out | every vendor agrees; the gateway's limit is lower |
| `claude-sonnet-4-6-eu` | ≥300,000 proven | config sits at 300,000; metadata claims 1M, untested above |
| Efforts, gpt-5.6 family | `none, low, medium, high, xhigh` | `max` refused here; `minimal` isn't a gpt-5.6 value |
| Efforts, Anthropic leg | `none, low, medium, high` | `xhigh` refused by the IU LiteLLM gateway |

**Reasoning effort only exists on the Responses API here.** `/v1/chat/completions` refuses any
effort once the request carries function tools — and Hermes always sends tools, so the effort
400s **every** turn, burns the retry budget and lands the conversation on the Anthropic fallback
while looking healthy. Hence `model.api_mode: codex_responses` + the runtime-provider patch.
**Tell:** `Fallback activated: gpt-5.6-luna → claude-sonnet-4-6-eu` every turn in
`~/.hermes/logs/agent.log`, with `Ignoring persisted custom api_mode=codex_responses for
non-OpenAI endpoint` one line above — that second line means the patch fell off, which is what a
`hermes update` does.

- **`agent.log` is not rotated per process** — slice every read at the current process start
  (`pgrep -f "hermes_cli.main gateway run"` → `ps -o lstart=`), or a days-old burst reads as
  current. `skills/hermes-gateway/` owns this (Rule 0 = the slicing; `references/model-routing.md`
  has the six settling commands). **Hermes may not restart its own gateway** — `hermes-ops.sh`
  excludes `ai.hermes.gateway`, and `claude-dispatch` is no workaround (no launchd authority).
- **The live key is `agent.reasoning_effort`, not `model.reasoning_effort`** —
  `resolve_reasoning_config()` (`hermes_constants.py`) reads `agent.reasoning_overrides` then
  `agent.reasoning_effort`; nothing reads the `model` copy. Both are `high` so a stale value
  can't be acted on; per-model overrides go in `agent.reasoning_overrides`.
- **The Anthropic fallback shares this base URL and must not follow it onto Responses** —
  `claude-sonnet-4-6-eu` 404s there. An explicit `api_mode` on a `fallback_providers` entry wins
  over URL detection, which is why that entry spells out `chat_completions`.
- **Compaction triggers at 240,000 tokens** (`compression.threshold_tokens`, absolute — the
  *lower* of ratio and absolute governs). Two ratio traps: a window **under 512K** floors its
  threshold at **0.75** (`_SMALL_CTX_THRESHOLD_PERCENT`), and the auxiliary compression model's
  own `context_length` **clamps the trigger down to itself** — hence
  `auxiliary.compression.context_length: 850000`, not the default 200,000. 240k also keeps
  prompts below the **272k mark where OpenAI bills input 2× and output 1.5×**.

Narrative: **`docs/model-context-reasoning.md`**.

## Shell script conventions

**Under `set -euo pipefail`, any `$(producer | head -c N)` substitution dies with SIGPIPE (141)
once `producer` exceeds `N` bytes** — `head` closes the pipe, `pipefail` makes the substitution
non-zero, `set -e` ends the script, and the crash happens before the first `echo` so there is no
log line. Guard **inside** the substitution: `$(git diff --cached | head -c 20000 || true)`. Any
new script piping an unbounded producer into `head -c`/`tail -c` under `pipefail` needs it.
The incident it came from: **`docs/shell-conventions.md`**.

## Setup

```bash
make setup        # idempotent — symlinks, LaunchAgents, CC skills
make status       # verify all of it (audio-gateway health, cron skill resolution, …)
make patch-check  # assert every patches/*.patch is applied to the live checkout
```

Prerequisites: `hermes` CLI installed (README.md §2) · `audio-gateway` reachable at
`…/health` · 1Password CLI authenticated as `tkrumm`. `make help` lists the rest
(`cron-migrate`, `agents-teardown`).

## Editing Rules

**Adding a Hermes skill:** create `skills/{name}/SKILL.md`, add `{name}` to `HERMES_SKILLS`, run
`make setup`. For scheduled briefings, also wire it into the relevant `cron/*.prompt.txt` and
re-sync `cron/jobs.json`.

**A new or renamed skill also needs a gateway restart.** The skills index in the system prompt
is cached **in-process** (`_SKILLS_PROMPT_CACHE`, `agent/prompt_builder.py`) keyed on directory
paths only, and nothing clears it except `skill_manager_tool` — so `hermes skills list` and the
disk snapshot both show the new skill while the running gateway cannot. Verify after restarting:
`./venv/bin/python3 -c "from agent.prompt_builder import build_skills_system_prompt as b; print('<name>' in b())"`.

**Renaming or retiring one fails silently.** A cron job preloads skills *by name*; an
unresolvable name logs `skill not found, skipping` at **WARNING**, the job runs anyway reporting
`ok`, and `watchdog-poll.py` matches `ERROR|CRITICAL` only. `make status` asserts every skill in
`~/.hermes/cron/jobs.json` resolves — **run it after any rename.**

**Three layers move together, only two are in git.** `cron/*.prompt.txt` and `cron/*.md` are
tracked; **`cron/jobs.json` is gitignored runtime state** and the live job holds its **own copy
of the prompt** — editing the `.txt` alone changes nothing at runtime. Push through the CLI,
never by hand-editing `jobs.json` under a running gateway:

```bash
hermes cron edit <job_id> --prompt "$(cat cron/morning-briefing.prompt.txt)"
hermes cron edit <job_id> --skill argo-api --skill work    # replaces the set
```

`--clear-skills` is applied *after* `--skill` and wins, leaving `Skills: none` — pass `--skill`
alone to replace a set. Verify with `hermes cron list`. `hermes cron run <job_id>` has **no
dry-run and delivers for real** — retarget first (`--deliver slack:<test-channel>`), then
restore. Detail: **`docs/scheduled-jobs.md`**.

**Adding a CC slash command:** create `.claude/skills/{name}/SKILL.md` — auto-loaded here, no
symlink or Makefile change. **Patches:** save the diff under `patches/`, add a table row in
*Local Modifications*, put per-file detail in `docs/patches.md`.
