# Hermes Agent — Mac Mini M2 Pro

Personal AI assistant running 24/7 on Mac Mini. Slack as interface, DeepSeek-V4-Pro as brain (EU; `claude-sonnet-4-6-eu` failover), eight skill domains.

**Hermes docs**: https://hermes-agent.nousresearch.com/docs/

## Architecture

```
Slack (Socket Mode)
  ↓
Mac Mini M2 Pro — Hermes Agent (always-on)
  ├→ audio-gateway (https://audio-gateway.jkrumm.com/v1) — OpenAI-compatible audio, EU-resident via IU.
  │     VPS Docker container, reached over the tailnet. No local audio service.
  │     TTS: Gemini 3.1 Flash, voice "Charon" (prep + chunk + MP3 internally).
  │     STT: gpt-4o-transcribe (German/English steered).
  ├→ Homelab — Docker containers, CouchDB, backups (via Tailscale)
  ├→ VPS — Production apps, ClickStack (via Tailscale)
  ├→ IU unified endpoint — DeepSeek-V4-Pro (primary, OpenAI-compat, EU; claude-sonnet-4-6-eu failover), DeepSeek-V4-Flash (auxiliaries)
  └→ Google AI Studio (direct, own key) — gemini-2.5-flash (vision)
```

## Channel Architecture

`allow_bots: all` + channel membership = ACL. Hermes processes every message in channels it's been invited to — human or bot. Keep external bots out of `#hermes`.

| Channel | ID | Hermes | External bots | Role |
|-|-|-|-|-|
| `#hermes` | C0ASRUD7K1U | read + write | HomeLab bot | Main conversation, HomeLab-triggered checks |
| `#inbox` | C0AT6TB49HP | read + write | HomeLab bot | Johannes + HomeLab drops (voice memos, links, digests) → Hermes processes |
| `#alerts` | C0AS1LAUQ3C | read + write | HomeLab bot, external monitors | Docker/UptimeKuma and other monitors fire in → Hermes triages and acts |
| `#watchdog` | C0ASRULFTSS | write only | — | Hermes posts its own proactive monitoring results (Phase 3) |
| `#briefings` | C0AT6TH404R | write only | — | Hermes posts morning/evening audio (Phase 1) |
| `#journal` | C0ATN8W6N2U | write only | — | Hermes posts structured journal entries (Phase 2) |
| `#news` | C0ASXJD0ZEG | write only | — | Daily digest (Phase 4) |

### Trigger Matrix

| Source | Channel | What happens |
|-|-|-|
| Johannes message | `#hermes` | Hermes responds immediately |
| Johannes voice memo / link | `#inbox` | Hermes transcribes / extracts + processes (Phase 2) |
| HomeLab bot drops digest/capture | `#inbox` | Hermes processes it the same as a manual drop |
| Docker / UptimeKuma alert | `#alerts` | Hermes calls argo-api, checks state, responds or escalates |
| External monitor alert | `#alerts` | Hermes triages, checks context, notifies if critical |
| Cron job | `#hermes` / `#briefings` | Hermes posts proactive update or audio briefing |
| Hermes monitoring loop | `#watchdog` | Hermes writes its own status checks (Phase 3, Hermes-initiated) |

### Bot Membership Rules

- **Hermes bot**: invited to all channels above
- **HomeLab bot**: `#hermes` + `#inbox` + `#alerts` — never `#watchdog`
- **Other external monitors**: `#alerts` only
- **Adding a new integration**: invite it to `#alerts` (reactive) or `#inbox` (data drops) — never `#hermes`

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

## Phase 0 — Foundation Setup

### 1. Mac Mini Prerequisites

```bash
# Prevent sleep (always-on agent host)
sudo pmset -a sleep 0 displaysleep 0 disksleep 0

# Verify audio-gateway — VPS Docker container, reached over the tailnet
curl -s https://audio-gateway.jkrumm.com/health
```

### 2. Install Hermes

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
hermes --version  # should show v0.12.0+
```

### 3. 1Password Vault

Create vault `hermes` in 1Password (account `tkrumm`) with items:
- `slack` — fields: `bot-token`, `app-token`
- `github` — field: `token` (PAT scoped to homelab/homelab-private/vps/dotfiles)

Existing items reused:
- `op://common/anthropic/API_KEY` — Anthropic (fallback LLM + auxiliary)
- `op://common/anthropic/BASE_URL` — Anthropic API base URL

### 4. Create Slack App

1. Go to https://api.slack.com/apps → Create New App → From scratch
2. Name: `Hermes`, Workspace: your personal workspace
3. **OAuth & Permissions** — add bot token scopes:
   - `chat:write`, `app_mentions:read`, `channels:history`, `channels:read`
   - `groups:history`, `im:history`, `im:read`, `im:write`
   - `users:read`, `files:write`, `files:read`
4. **Socket Mode** — enable, create app-level token (scope: `connections:write`)
5. **Event Subscriptions** — enable, subscribe to bot events:
   - `app_mention`, `message.channels`, `message.groups`, `message.im`
6. Install to workspace, copy Bot Token + App Token to 1Password `hermes/slack`

### 5. Create Slack Channels

Create these channels and invite the Hermes bot:
- `#hermes` — interactive, main conversation
- `#inbox` — journal captures, voice memos, links
- `#journal` — structured journal output
- `#watchdog` — infra alerts (Phase 3)
- `#news` — daily news digest (Phase 4)
- `#briefings` — morning/evening audio reports (Phase 1)

### 6. Deploy Config

```bash
# Mac Mini-only — symlinks all hermes config files and registers the
# liveness + backup crons. TTS/STT is served by the audio-gateway
# (https://audio-gateway.jkrumm.com/v1), a VPS Docker container reached over the
# tailnet — Hermes just points its native openai TTS/STT providers at it (see config.yaml).
cd ~/SourceRoot/hermes-agent && make setup

# Verify
make status
```

`make setup` runs idempotently. Re-run after editing skills or cron scripts.
Crontab entries are rewritten in place — existing hermes lines are replaced,
unrelated entries are preserved.

### 7. Run Hermes Setup

```bash
hermes setup  # interactive — confirm LLM provider, voice, Slack
```

### 8. Start the Gateway

```bash
hermes gateway install   # registers the LaunchAgent (label: ai.hermes.gateway) and starts the gateway
```

> **launchd caveat (this macOS).** `hermes gateway install` (and `restart`) cannot
> bootstrap the user-domain LaunchAgent here — it fails with
> `Bootstrap failed: 5: I/O error` and the CLI automatically falls back to a healthy
> bare background process (`hermes gateway run --replace`). Consequence: **no
> auto-restart on crash and no start-at-login.** The safety net is the liveness cron
> (every 5 min, §"Cron — Liveness + Backup") → UptimeKuma push monitor
> `Hermes Agent - Push`, which alerts on a missing heartbeat if the gateway dies.

(Re)start manually with:

```bash
hermes gateway restart   # launchd-supervised (auto-restart on crash, start at login)
```

Verify it's up:

```bash
curl -s "http://$(secrets-run read op://hermes/gateway/host):8642/health"
tail -20 ~/.hermes/logs/gateway.log  # watch for successful Slack connection
```

### 9. Verify

- [x] Send message in `#hermes` on Slack — get response via DeepSeek-V4-Pro
- [x] Send voice memo in Slack — get transcribed via audio-gateway (`gpt-4o-transcribe`)
- [x] TTS audio generation — Gemini Charon via audio-gateway, MP3 output
- [x] Backup cron — daily 03:00 rsync to `homelab:/mnt/hdd/backups/hermes/`, pings UK
- [x] Liveness cron — every 5 min, pings UK if gateway running + Slack connected

### Known Issues / TODOs

- **`hermes gateway install` prints `Bootstrap failed: 5: Input/output error`** several times while repairing the service definition. That message is **noise** — it finishes with `✓ Service definition updated`, and `hermes gateway status` then reports `✓ Gateway is supervised by launchd`. Auto-start at login and auto-restart on crash do work. Check `gateway status` for the real state; never `launchctl load` the plist by hand.
- **Secrets fail soft, not closed.** If `secrets.command` can't resolve, the gateway still starts — just credential-less — so treat `Command helper: applied N secrets` as a required check after any secrets change (see below).

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
make status                       # → ✓ secrets (26 refs via secrets-run cache)
hermes gateway status             # → Command helper: applied 26 secrets

# If either is missing, test the helper in isolation:
secrets-run export --env-file=~/.hermes/.env.tpl | sed 's/^export //' | wc -l
```

To add a secret: add the `KEY=op://vault/item/field` line to `.env.tpl`, add the same
`op://` ref to `dotfiles-private/headless.refs`, then re-seed the cache (`make secrets-seed`
— biometric, must run with a human present). A ref absent from `headless.refs` will never
resolve on the mini; that allowlist *is* the security boundary.

## Cron — Liveness + Backup

Both installed by `make setup`. Both ping UptimeKuma push monitors.

| When | Script | What |
|-|-|-|
| `*/5 * * * *` | `scripts/hermes-liveness.sh` | Read `~/.hermes/gateway_state.json`. If `gateway_state == "running"` AND `platforms.slack.state == "connected"` AND PID alive → curl the push URL (resolved via `secrets-run read op://hermes/uptime-kuma/agent-push-url`). UK monitor `Hermes Agent - Push` (interval 360s). |
| `0 3 * * *` | `scripts/hermes-backup.sh` | rsync `~/.hermes/` → `homelab:/mnt/hdd/backups/hermes/` (excludes `audio_cache/`, `image_cache/`, `cache/`, `sandboxes/`, `sessions/`, `hermes-agent/`, `*.lock`, `*.pid`). On success → curl the push URL (resolved via `secrets-run read op://hermes/uptime-kuma/backup-push-url`). UK monitor `Hermes Backup - Push` (interval 25h). |

**Push URLs** live in 1Password (`op://hermes/uptime-kuma/{agent,backup,watchdog}-push-url`) and are resolved **on demand** by each script via `secrets-run read` — the drop-in `op` shim (encrypted cache on the Mac mini, biometric `op` on the MacBook), so no plaintext `~/.hermes/.env` is needed. cron runs with a minimal `PATH`, so the scripts prepend `/opt/homebrew/bin` (secrets-run's cache backend needs `sops`+`jq`). Scripts no-op silently if the URL can't be resolved — UK alerts on the missing heartbeat. The watchdog heartbeat (`UPTIME_PUSH_WATCHDOG`) is pinged by `scripts/watchdog-slack.py` on a clean 30-min poll; UK monitor `Hermes Watchdog - Push` (interval ~2700s). The watchdog resolves its own secrets (`GITHUB_TOKEN`, `HOMELAB_API_KEY`, `UPTIME_PUSH_WATCHDOG`) the same way — inheriting whatever survives the gateway subprocess sanitizer and backfilling the rest from the cache (`scripts/watchdog-poll.py:load_env`).

**Push monitors** are created manually in the UK UI per existing convention (uptime-kuma-api 1.2.1 doesn't support UK 2.x push creation). Monitor specs are documented declaratively in `homelab/uptime-kuma/monitors.yaml` under the Infrastructure subgroup.

**Restic / B2:** Duplicati already mounts `/mnt:/source/mnt`, so `/mnt/hdd/backups/hermes/` is picked up by the existing B2 backup job.

## Phases

| Phase | Domain | Status |
|-|-|-|
| 0 | Foundation (Hermes + Slack + LLM + Voice) | **Done** (2026-04-14) |
| 1 | Assistant (TickTick, Calendar, Briefings) | **Next** |
| 2 | Journal (Voice memos, Obsidian, Mood) | Planned |
| 3 | Watchdog (Docker, UptimeKuma, GitHub Issues) | Planned |
| 4 | News (RSS, YouTube, Reddit, Dedup) | Planned |
