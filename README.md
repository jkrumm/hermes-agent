# Hermes Agent — Mac Mini M2 Pro

Personal AI assistant running 24/7 on Mac Mini. Slack as interface, Gemma 4 on M2 Max as brain, four skill domains (assistant, journal, watchdog, news).

**PRD**: `../hermes-agent-prd.md`
**Hermes docs**: https://hermes-agent.nousresearch.com/docs/

## Architecture

```
Slack (Socket Mode)
  ↓
Mac Mini M2 Pro — Hermes Agent (always-on)
  ├→ M2 Max MacBook — Gemma 4 (LLM), Whisper (STT), Kokoro/Qwen3 (TTS)
  ├→ Homelab — Docker containers, CouchDB, backups
  ├→ VPS — Production apps, ClickStack
  └→ Anthropic API — Sonnet (fallback LLM), Haiku (auxiliary: compression, vision)
All connected via Tailscale.
```

## Files

| File | Purpose | Deploy to |
|-|-|-|
| `config.yaml` | Main config template | `~/.hermes/config.yaml` |
| `.env.tpl` | 1Password secret references | `~/.hermes/.env.tpl` |
| `SOUL.md` | Agent identity | `~/.hermes/SOUL.md` |
| `USER.md` | User preferences | `~/.hermes/memories/USER.md` |
| `skills/` | Skill definitions (Phase 1+) | `~/.hermes/skills/` (symlink) |

## Phase 0 — Foundation Setup

### 1. Mac Mini Prerequisites

```bash
# Prevent sleep (always-on agent host)
sudo pmset -a sleep 0 displaysleep 0 disksleep 0

# Verify Tailscale — must reach M2 Max
ping iu-mac-book.dinosaur-sole.ts.net
curl -s https://iu-mac-book.dinosaur-sole.ts.net/v1/models  # should list gemma4-agent
```

### 2. Install Hermes

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
hermes --version  # should show v0.9.0+
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
# Copy templates to Mac Mini ~/.hermes/
cp config.yaml ~/.hermes/config.yaml
cp .env.tpl ~/.hermes/.env.tpl
cp SOUL.md ~/.hermes/SOUL.md
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

- [ ] Send message in `#hermes` on Slack — get response via Gemma 4
- [ ] Send voice memo in Slack — get transcribed + spoken response
- [ ] Kill M2 Max Ollama — verify fallback to Anthropic Claude
- [ ] `hermes config check` — no missing options
- [ ] Web dashboard accessible at `http://localhost:PORT` (v0.9.0+)

## Backup

```bash
# Daily rsync to homelab (add to crontab on Mac Mini)
# 0 3 * * * rsync -az --exclude='*.mp3' ~/.hermes/ homelab:~/hermes-backup/
```

Homelab → Backblaze B2 via existing restic schedule picks up `~/hermes-backup/`.

## Phases

| Phase | Domain | Status |
|-|-|-|
| 0 | Foundation (Hermes + Slack + LLM + Voice) | **Active** |
| 1 | Assistant (TickTick, Calendar, Briefings) | Planned |
| 2 | Journal (Voice memos, Obsidian, Mood) | Planned |
| 3 | Watchdog (Docker, UptimeKuma, GitHub Issues) | Planned |
| 4 | News (RSS, YouTube, Reddit, Dedup) | Planned |
