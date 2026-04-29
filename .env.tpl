# Hermes Agent — secrets template
# Resolved via: op run --account tkrumm --env-file=.env.tpl -- hermes gateway start
# Copy to ~/.hermes/.env.tpl on Mac Mini

# Slack (create app via manifest: hermes/slack-app-manifest.json)
SLACK_BOT_TOKEN=op://hermes/slack/bot-token
SLACK_APP_TOKEN=op://hermes/slack/app-token
SLACK_ALLOWED_USERS=op://hermes/slack/allowed-user-id
SLACK_ALLOW_ALL_USERS=true        # Channel membership is the ACL — no per-user ID filtering needed
# Channel IDs — fill after creating channels (Settings > Copy Channel ID)
SLACK_CHANNEL_HERMES=op://hermes/slack/channel-hermes
SLACK_HOME_CHANNEL=op://hermes/slack/channel-hermes
SLACK_CHANNEL_INBOX=op://hermes/slack/channel-inbox

# Anthropic — fallback LLM via IU company proxy
ANTHROPIC_API_KEY=op://common/anthropic/API_KEY
ANTHROPIC_BASE_URL=op://common/anthropic/BASE_URL

# Google AI Studio — vision only (Anthropic endpoint doesn't support images)
GEMINI_API_KEY=op://hermes/google-ai-studio/api-key

# Tavily — web search, extract, crawl (replaces browser-based search)
TAVILY_API_KEY=op://hermes/tavily/API_KEY

# Voice — dummy key for OpenAI-compatible TTS/STT on M2 Max (Tailscale handles auth)
VOICE_TOOLS_OPENAI_KEY=not-needed

# GitHub — issue creation, repo queries (watchdog, Phase 3)
GITHUB_TOKEN=op://hermes/github/token

# Homelab API — single integration layer for TickTick, Gmail, Calendar, Docker, UptimeKuma, Slack
# Replaces separate MCP servers for Phase 1 + Phase 3. Base URL: https://api.jkrumm.com
HOMELAB_API_KEY=op://common/api/SECRET

# UptimeKuma push URLs — consumed by hermes/scripts/{hermes-liveness,hermes-backup}.sh
# Push monitors created manually in UK UI; URLs stored in 1Password after creation.
UPTIME_PUSH_HERMES=op://hermes/uptime-kuma/agent-push-url
UPTIME_PUSH_BACKUP=op://hermes/uptime-kuma/backup-push-url

# Cron job idle timeout — hermes-agent/cron/scheduler.py kills any cron job that goes idle
# (no tool activity / agent thinking) for this long. Default 600s is too tight for the
# morning briefing's long-form German Fish S2 Pro TTS run; 1800s gives headroom.
HERMES_CRON_TIMEOUT=1800
