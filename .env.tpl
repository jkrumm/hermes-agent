# Hermes Agent — secrets template
# Resolved via: op run --account tkrumm --env-file=.env.tpl -- hermes gateway start
# Copy to ~/.hermes/.env.tpl on Mac Mini

# API server (gateway HTTP surface) — exposes the gateway on the tailnet so the
# argo VPS dashboard chat can reach it (argo: HERMES_BASE_URL=http://<host>:8642/v1).
# HOST is the Mac Mini's Tailscale IP (tailnet-only bind, no LAN listener); a
# Tailscale ACL grants tag:vps → tag:mac on tcp:8642. KEY auth-gates every request
# (even loopback) and MUST equal argo's HERMES_API_KEY (op://vps/argo/HERMES_API_KEY)
# — this op item is the canonical source. HOST is an op:// ref too, to keep the
# Tailscale IP out of git (security rule).
API_SERVER_ENABLED=true
API_SERVER_HOST=op://hermes/gateway/host
API_SERVER_PORT=8642
API_SERVER_KEY=op://hermes/gateway/api-server-key

# Slack (create app via manifest: hermes/slack-app-manifest.json)
SLACK_BOT_TOKEN=op://hermes/slack/bot-token
SLACK_APP_TOKEN=op://hermes/slack/app-token
SLACK_ALLOWED_USERS=op://hermes/slack/allowed-user-id
SLACK_ALLOW_ALL_USERS=true        # Channel membership is the ACL — no per-user ID filtering needed
# Channel IDs — fill after creating channels (Settings > Copy Channel ID)
SLACK_CHANNEL_HERMES=op://hermes/slack/channel-hermes
SLACK_HOME_CHANNEL=op://hermes/slack/channel-hermes
SLACK_CHANNEL_INBOX=op://hermes/slack/channel-inbox

# Kimi brain (default) — IU unified endpoint, OpenAI-compatible transport.
# Same key as ANTHROPIC_*; the base is the OpenAI-compat surface (…/openai/v1),
# DERIVED from BASE_URL (…/anthropic → …/openai/v1). NOTE: the runtime reads the
# resolved ~/.hermes/.env (rebuilt by the Python builder in README.md, which
# derives this value); this literal is the documented template only.
OPENAI_API_KEY=op://common/anthropic/API_KEY
OPENAI_BASE_URL=https://unified-endpoint-main.app.iu-it.org/openai/v1

# Anthropic — auxiliary models only (Haiku: web_extract / compression / approval
# / title_generation). The IU company proxy serves Anthropic Messages here.
ANTHROPIC_API_KEY=op://common/anthropic/API_KEY
ANTHROPIC_BASE_URL=op://common/anthropic/BASE_URL

# Google AI Studio — vision only (Anthropic endpoint doesn't support images)
GEMINI_API_KEY=op://hermes/google-ai-studio/api-key

# Tavily — web search, extract, crawl (replaces browser-based search)
TAVILY_API_KEY=op://hermes/tavily/API_KEY

# Voice — api_key the native openai TTS/STT tools send to audio-proxy (:7716).
# audio-proxy runs with PROXY_API_KEY empty (localhost-only), so any value works.
VOICE_TOOLS_OPENAI_KEY=not-needed

# GitHub — issue creation, repo queries (watchdog, Phase 3)
GITHUB_TOKEN=op://hermes/github/token

# Argo API (formerly homelab API) — single integration layer for TickTick, Gmail,
# Calendar, Docker, UptimeKuma, Slack. Base URL: https://argo.jkrumm.com/api
# (env var name HOMELAB_API_KEY kept for shell/cron compatibility)
HOMELAB_API_KEY=op://common/api/SECRET

# UptimeKuma push URLs — pinged on success by hermes-liveness.sh, hermes-backup.sh,
# and watchdog-slack.py. Push monitors created manually in UK UI; URLs stored in
# 1Password after creation. Watchdog monitor interval ~2700s (45 min) — 30 min cron
# + grace, so one missed run alerts without flapping.
UPTIME_PUSH_HERMES=op://hermes/uptime-kuma/agent-push-url
UPTIME_PUSH_BACKUP=op://hermes/uptime-kuma/backup-push-url
UPTIME_PUSH_WATCHDOG=op://hermes/uptime-kuma/watchdog-push-url

# Cron job idle timeout — hermes-agent/cron/scheduler.py kills any cron job that goes idle
# (no tool activity / agent thinking) for this long. Default 600s is too tight for the
# morning briefing's long-form German TTS run (audio-proxy chunks + synthesizes a
# multi-paragraph narrative); 1800s gives headroom.
HERMES_CRON_TIMEOUT=1800
