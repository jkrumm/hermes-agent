# Hermes Agent — Mac Mini M2 Pro

Personal AI assistant running 24/7 on Mac Mini. Chat through Iris, Claude Haiku 5.5 (high) as brain on the agent-workflows inference gateway's Anthropic leg (`gpt-6-luna` failover), twenty skill domains (`HERMES_SKILLS` in the Makefile is the count).

For repo-operating detail (repo work, secrets, patches, model routing), see `AGENTS.md`.

**Hermes docs**: https://hermes-agent.nousresearch.com/docs/

## Architecture

```
Iris (chat + voice memos) ──→ API server :8642 (tailnet)
Hermes Desktop ─────────→ `hermes serve` :9119 (behind the Caddy door)
CLI (`hermes chat`)
  ↓
Mac Mini M2 Pro — Hermes Agent (always-on)
  ├→ audio door (http://127.0.0.1:7792/v1) — OpenAI-compatible audio via IU (agent-workflows audio process, loopback).
  │     Bearer from the local door-token file. No audio service in this repo.
  │     TTS: ElevenLabs via IU Replicate — flash-v2.5 for replies, v3 for briefings, voice "Mark".
  │     STT: gpt-transcribe (German/English steered).
  ├→ Homelab — Docker containers, CouchDB, backups (via Tailscale)
  ├→ VPS — Production apps, ClickStack (via Tailscale)
  └→ inference gateway (http://127.0.0.1:7794, agent-workflows) — Claude credit pools first, IU after:
        claude-haiku-5-5 (brain, compression, title_generation, approval) and claude-sonnet-5-5 (vision)
        over /anthropic; gpt-6-luna (fallback) over /openai/v1
```

## Surfaces

| Surface | How | Role |
|-|-|-|
| Iris | Phone voice-memo/chat app; calls the API server on `:8642` (pull-only, Hermes cannot push to it) | Chat and voice memos |
| Hermes Desktop | `hermes serve` (`:9119`, `com.jkrumm.hermes-serve`) | Desktop chat on the MacBook |
| CLI | `hermes chat` on the mini | Ad-hoc use and tests |
| ntfy | Topics `briefings` (project narratives, usage weekly report), `watchdog` (brain drift audit) and `models` (model release watch); every topic is listed in the homelab repo's `docs/ntfy.md` | Notices. Hermes has no ntfy platform: each cron job runs with `--deliver local` and publishes itself through `scripts/ntfy-publish.sh` |

There is no Slack gateway any more (removed 2026-11): no bot, tokens or channels. Fleet and Issue
state is read through the `factory` CLI (`factory read overview|needs|flow|chain|issues|issue <id>|asks|health|sessions|accounts|friction`),
and agent work is filed with `factory signal file`.

## Files

| File | Live path | How |
|-|-|-|
| `config.yaml` | `~/.hermes/config.yaml` | symlink |
| `.env.tpl` | `~/.hermes/.env.tpl` | symlink |
| `SOUL.md` | `~/.hermes/SOUL.md` | symlink |
| `USER.md` | `~/.hermes/memories/USER.md` | copied — Hermes writes to it |
| `skills/{name}/` | `~/.hermes/skills/{name}/` | symlink per skill |
| `cron/` | `~/.hermes/cron/` | symlink |
| `hooks/` | `~/.hermes/hooks/` | symlink |

## Setup

### 1. Mac Mini Prerequisites

```bash
# Prevent sleep (always-on agent host)
sudo pmset -a sleep 0 displaysleep 0 disksleep 0

# Verify the audio door — agent-workflows audio process on the mini
curl -s http://127.0.0.1:7792/health
```

### 2. Install Hermes

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
hermes --version  # should show v0.21.0+ (the version this repo's patches target)
```

### 3. 1Password Vault

Create vault `hermes` in 1Password (account `tkrumm`) with items:
- `github` — field: `token` (PAT scoped to homelab/homelab-private/vps/dotfiles)

Existing items reused:
- `op://common/anthropic/API_KEY` — Anthropic (fallback LLM + auxiliary)
- `op://common/anthropic/BASE_URL` — Anthropic API base URL

### 4. Deploy Config

```bash
# Mac Mini-only — symlinks all hermes config files and installs the
# liveness + backup LaunchAgents. TTS/STT is served by the agent-workflows audio door
# (http://127.0.0.1:7792/v1, loopback) — Hermes just points its native openai
# TTS/STT providers at it (see config.yaml).
cd ~/SourceRoot/hermes-agent && make setup

# Verify
make status
```

`make setup` runs idempotently and **non-interactively** — nothing in it blocks on a
TCC prompt, so it can be driven by an agent on the headless mini rather than only by a
human at the screen. Re-run after editing skills or cron scripts. A LaunchAgent whose
rendered plist is unchanged is left alone, so re-running never bounces a healthy job.

### 5. Run Hermes Setup

```bash
hermes setup  # interactive — confirm LLM provider, voice
```

### 6. Start the Gateway

```bash
hermes gateway install   # registers the LaunchAgent (label: ai.hermes.gateway) and starts the gateway
```

> **`Bootstrap failed: 5` is noise.** `hermes gateway install` still prints it while
> repairing the service definition, and it used to mean the CLI had fallen back to a
> bare background process with no auto-restart and no start-at-login. Since v0.19.0 it
> does not: `hermes gateway status` reports the gateway genuinely **supervised by
> launchd**, so both are live. Trust `gateway status`, not the install output. The
> liveness agent (every 5 min, §"Scheduled jobs") → UptimeKuma `Hermes Agent - Push`
> remains the backstop for a gateway that dies in a way launchd cannot recover.

(Re)start manually with:

```bash
hermes gateway restart   # launchd-supervised (auto-restart on crash, start at login)
```

Verify it's up:

```bash
curl -s "http://$(secrets-run read op://hermes/gateway/host):8642/health"
tail -20 ~/.hermes/logs/gateway.log  # watch for the API server platform coming up
```

### 7. Verify

- [x] Send a message in Iris (or `hermes chat -q "ping"`) — get a response
- [x] Send a voice memo in Iris — get transcribed via the audio door (`gpt-4o-transcribe`)
- [x] TTS audio generation — ElevenLabs (flash-v2.5 / v3, voice Mark) via the audio door, MP3 output
- [x] Backup agent — daily 03:00 rsync to `homelab:/mnt/hdd/backups/hermes/`, pings UK
- [x] Liveness agent — every 5 min, pings UK if gateway running + API server connected

### Secrets — no `.env`, no wrapper

There is deliberately **no `~/.hermes/.env`** and no launch wrapper. Hermes resolves its own
secrets at startup via v0.19's `SecretSource` interface (`config.yaml` → `secrets.command`),
which shells out to the dotfiles `secrets-run` shim — the drop-in `op` replacement backed by
an age-encrypted offline cache on this headless Mac mini (a direct `op read` here would hang
on the biometric prompt). `.env.tpl` remains the single list of `KEY=op://…` refs; it is now
consumed by that source rather than by an `op run` wrapper.

This also means **every** hermes invocation gets secrets — gateway, CLI, and cron alike —
so ad-hoc debugging works without hand-wrapping commands.

```bash
make status                       # → ✓ secrets (28 refs via secrets-run cache)
hermes gateway status             # → Command helper: applied 28 secrets

# If either is missing, test the helper in isolation:
secrets-run export --env-file=~/.hermes/.env.tpl | sed 's/^export //' | wc -l
```

To add a secret: add the `KEY=op://vault/item/field` line to `.env.tpl`, add the same
`op://` ref to `dotfiles-private/headless.refs`, then re-seed the cache (`make secrets-seed`
— biometric, must run with a human present). A ref absent from `headless.refs` will never
resolve on the mini; that allowlist *is* the security boundary.

## Scheduled jobs — Liveness + Backup

Both installed by `make setup` as **user LaunchAgents** (templates in `launchd/`,
rendered into `~/Library/LaunchAgents`). Both ping UptimeKuma push monitors.

They ran under macOS `crontab` until 2026-08-02. The move is not cosmetic: a
`crontab -` *write* needs Full Disk Access on the invoking process, so on the
headless mini `make setup` raised a TCC dialog nobody could answer and blocked
indefinitely — even when the entries were already correct. launchd needs no such
grant. Clearing the old entries is itself a `crontab -` write and so lives behind a
separate one-time `make cron-migrate` (bounded by `timeout`, run it from a terminal
with Full Disk Access); `make status` flags them until it succeeds.

| When | Script | What |
|-|-|-|
| every 300s (`StartInterval`) | `scripts/hermes-liveness.sh` | Read `~/.hermes/gateway_state.json`. If `gateway_state == "running"` AND `platforms.api_server.state == "connected"` AND PID alive AND the agw inference gateway (`:7794`) answers and accepts the `hermes=` door token (`scripts/inference-gateway-check.sh`) → curl the push URL (resolved via `secrets-run read op://hermes/uptime-kuma/agent-push-url`). UK monitor `Hermes Agent - Push` (interval 360s). |
| 03:00 daily (`StartCalendarInterval`) | `scripts/hermes-backup.sh` | rsync `~/.hermes/` → `homelab:/mnt/hdd/backups/hermes/` (excludes `audio_cache/`, `image_cache/`, `cache/`, `sandboxes/`, `sessions/`, `hermes-agent/`, `*.lock`, `*.pid`). Holds a `mkdir` single-instance lock so overlapping runs can't race `rsync --delete`. On success → curl the push URL (resolved via `secrets-run read op://hermes/uptime-kuma/backup-push-url`). UK monitor `Hermes Backup - Push` (interval 25h). |

**Push URLs** live in 1Password (`op://hermes/uptime-kuma/{agent,backup,watchdog}-push-url`) and are resolved **on demand** by each script via `secrets-run read` — the drop-in `op` shim (encrypted cache on the Mac mini, biometric `op` on the MacBook), so no plaintext `~/.hermes/.env` is needed. launchd hands a job a minimal `PATH` (as cron did), so the scripts prepend `/opt/homebrew/bin` (secrets-run's cache backend needs `sops`+`jq`). Scripts no-op silently if the URL can't be resolved — UK alerts on the missing heartbeat. The watchdog push URL (`UPTIME_PUSH_WATCHDOG`) has no pinger since the out-of-band watchdog poller was retired.

**Push monitors** are created manually in the UK UI per existing convention (uptime-kuma-api 1.2.1 doesn't support UK 2.x push creation). Monitor specs are documented declaratively in `homelab/uptime-kuma/monitors.yaml` under the Infrastructure subgroup.

**Restic / B2:** Duplicati already mounts `/mnt:/source/mnt`, so `/mnt/hdd/backups/hermes/` is picked up by the existing B2 backup job.

Every Hermes cron job (morning briefing and evening report, both paused; brain drift audit, project
narratives, model release watch, usage weekly report) is listed with its id in the registry table in `docs/scheduled-jobs.md`; `make
status` asserts the live set matches it.

## Repo work is filed

Hermes triages well but reads a repo badly — it has no access to a repo's `AGENTS.md`/`CLAUDE.md`,
`.claude/rules/` or `.claude/skills/`. For anything that needs real repo context (a bug fix,
an investigation, a PR), Hermes files a GitHub issue (`capture`) and answers in one line; the owner starts
the work. Herdr tabs (`hc`/`rd`, the `herdr` skill) only on request; larger plans go to the factory (`factory signal file`).
Details: `AGENTS.md` §Repo work is filed.
