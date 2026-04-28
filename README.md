# Hermes Agent — Mac Mini M2 Pro

Personal AI assistant running 24/7 on Mac Mini. Slack as interface, Gemma 4 on M2 Max as brain, four skill domains (assistant, journal, watchdog, news).

**PRD**: `../hermes-agent-prd.md`
**Hermes docs**: https://hermes-agent.nousresearch.com/docs/

## Architecture

```
Slack (Socket Mode)
  ↓
Mac Mini M2 Pro — Hermes Agent (always-on)
  ├→ mlx-audio (127.0.0.1:8000) — Parakeet TDT v3 (STT), Kokoro/Qwen3 (TTS)
  ├→ Homelab — Docker containers, CouchDB, backups (via Tailscale)
  ├→ VPS — Production apps, ClickStack (via Tailscale)
  └→ IU unified endpoint — Sonnet 4.6 (primary), Haiku 4.5 (auxiliary), Gemini Flash (vision)
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
| Docker / UptimeKuma alert | `#alerts` | Hermes calls homelab-api, checks state, responds or escalates |
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

# Verify mlx-audio — should be running locally after `make _setup-localai`
curl -s http://127.0.0.1:8000/v1/models
```

### 2. Install Hermes

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
hermes --version  # should show v0.11.0+
```

### 3. 1Password Vault

Create vault `hermes` in 1Password (account `tkrumm`) with items:
- `slack` — fields: `bot-token`, `app-token`
- `github` — field: `token` (PAT scoped to homelab/homelab-private/vps/claude-local)

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
# Symlink config files to Mac Mini ~/.hermes/
REPO=~/SourceRoot/claude-local/hermes
ln -sf $REPO/config.yaml ~/.hermes/config.yaml
ln -sf $REPO/.env.tpl ~/.hermes/.env.tpl
ln -sf $REPO/SOUL.md ~/.hermes/SOUL.md
ln -sf $REPO/cron ~/.hermes/cron
ln -sf $REPO/hooks ~/.hermes/hooks
# Skills: symlink each custom skill individually
ln -sf $REPO/skills/homelab-api ~/.hermes/skills/homelab-api
ln -sf $REPO/skills/infrastructure ~/.hermes/skills/infrastructure
ln -sf $REPO/skills/tasks ~/.hermes/skills/tasks
ln -sf $REPO/skills/schedule ~/.hermes/skills/schedule
ln -sf $REPO/skills/weather ~/.hermes/skills/weather
ln -sf $REPO/skills/slack ~/.hermes/skills/slack
ln -sf $REPO/skills/localai-debug ~/.hermes/skills/localai-debug
# USER.md: copy (not symlink) — Hermes writes to this file
mkdir -p ~/.hermes/memories
cp USER.md ~/.hermes/memories/USER.md

# Verify secrets resolve
op run --account tkrumm --env-file=~/.hermes/.env.tpl -- env | grep SLACK
```

### 7. Run Hermes Setup

```bash
hermes setup  # interactive — confirm LLM provider, voice, Slack
```

### 8. Start Gateway (LaunchAgent)

Create `~/Library/LaunchAgents/com.hermes.gateway.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hermes.gateway</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-c</string>
        <string>op run --account tkrumm --env-file=$HOME/.hermes/.env.tpl -- hermes gateway start</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/hermes-gateway.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/hermes-gateway.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.hermes.gateway.plist
tail -f /tmp/hermes-gateway.log  # watch for successful Slack connection
```

### 9. Verify

- [x] Send message in `#hermes` on Slack — get response via Gemma 4
- [x] Send voice memo in Slack — get transcribed via Whisper STT
- [x] TTS audio generation via Kokoro — uploads as Ogg Vorbis file
- [ ] Fallback to Anthropic Claude when M2 Max is offline
- [ ] Backup cron — daily rsync to homelab

### Known Issues / TODOs

- **TTS format**: Kokoro outputs Ogg Vorbis — Slack shows as download, not inline player. Investigate mp3/m4a output for inline playback.
- **Gateway launchd**: `hermes gateway restart` sometimes doesn't reload. Use `hermes gateway stop && hermes gateway start` as workaround.
- **`.env` rebuild**: API keys with `=` chars break shell splitting. Use the Python builder script (see below) instead of `op run ... env > .env`.

```bash
# Rebuild ~/.hermes/.env from 1Password (handles keys with = chars)
python3 -c "
import subprocess, os
refs = {
    'SLACK_BOT_TOKEN': 'op://hermes/slack/bot-token',
    'SLACK_APP_TOKEN': 'op://hermes/slack/app-token',
    'SLACK_ALLOWED_USERS': 'op://hermes/slack/allowed-user-id',
    'SLACK_CHANNEL_HERMES': 'op://hermes/slack/channel-hermes',
    'SLACK_HOME_CHANNEL': 'op://hermes/slack/channel-hermes',
    'SLACK_CHANNEL_INBOX': 'op://hermes/slack/channel-inbox',
    'ANTHROPIC_API_KEY': 'op://common/anthropic/API_KEY',
    'ANTHROPIC_BASE_URL': 'op://common/anthropic/BASE_URL',
    'GEMINI_API_KEY': 'op://hermes/google-ai-studio/api-key',
    'TAVILY_API_KEY': 'op://hermes/tavily/API_KEY',
    'GITHUB_TOKEN': 'op://hermes/github/token',
    'HOMELAB_API_KEY': 'op://common/api/SECRET',
}
# Static env vars (not from 1Password)
static = {
    'VOICE_TOOLS_OPENAI_KEY': 'not-needed',  # Dummy key for OpenAI-compatible TTS/STT on M2 Max
}
lines = []
for key, ref in refs.items():
    val = subprocess.check_output(['op', 'read', ref, '--account', 'tkrumm'], text=True).strip()
    lines.append(f'{key}={val}')
for key, val in static.items():
    lines.append(f'{key}={val}')
with open(os.path.expanduser('~/.hermes/.env'), 'w') as f:
    f.write('\n'.join(lines) + '\n')
os.chmod(os.path.expanduser('~/.hermes/.env'), 0o600)
print(f'Written {len(lines)} secrets')
"
```

## Backup

```bash
# Daily rsync to homelab (add to crontab on Mac Mini)
# 0 3 * * * rsync -az --exclude='*.mp3' ~/.hermes/ homelab:~/hermes-backup/
```

Homelab → Backblaze B2 via existing restic schedule picks up `~/hermes-backup/`.

## Phases

| Phase | Domain | Status |
|-|-|-|
| 0 | Foundation (Hermes + Slack + LLM + Voice) | **Done** (2026-04-14) |
| 1 | Assistant (TickTick, Calendar, Briefings) | **Next** |
| 2 | Journal (Voice memos, Obsidian, Mood) | Planned |
| 3 | Watchdog (Docker, UptimeKuma, GitHub Issues) | Planned |
| 4 | News (RSS, YouTube, Reddit, Dedup) | Planned |
