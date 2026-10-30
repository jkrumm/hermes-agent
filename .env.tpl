# Hermes Agent — secrets template
# Resolved via: op run --account tkrumm --env-file=.env.tpl -- hermes gateway start
# Copy to ~/.hermes/.env.tpl on Mac Mini

# API server (gateway HTTP surface) — iris (on the mini) delivers memos through it.
# HOST is the Mac Mini's Tailscale IP (tailnet-only bind, no LAN listener); the argo VPS
# grant on tcp:8642 was removed 2026-10-30 with the dashboard chat. KEY auth-gates every
# request (even loopback); iris reads the same op item as HERMES_TOKEN. HOST is an op://
# ref too, to keep the Tailscale IP out of git (security rule).
API_SERVER_ENABLED=true
API_SERVER_HOST=op://hermes/gateway/host
API_SERVER_PORT=8642
API_SERVER_KEY=op://hermes/gateway/api-server-key
# Name advertised on /v1/models (default would be 'hermes-agent').
API_SERVER_MODEL_NAME=hermes

# Slack (create app via manifest: hermes/slack-app-manifest.json)
SLACK_BOT_TOKEN=op://hermes/slack/bot-token
SLACK_APP_TOKEN=op://hermes/slack/app-token
SLACK_ALLOWED_USERS=op://hermes/slack/allowed-user-id
SLACK_ALLOW_ALL_USERS=true        # Channel membership is the ACL — no per-user ID filtering needed
# Channel IDs — fill after creating channels (Settings > Copy Channel ID)
SLACK_CHANNEL_HERMES=op://hermes/slack/channel-hermes
SLACK_HOME_CHANNEL=op://hermes/slack/channel-hermes
SLACK_CHANNEL_INBOX=op://hermes/slack/channel-inbox

# gpt-6-luna fallback/compression/title_generation and
# gemini-3.5-flash vision — all on the IU unified endpoint's OpenAI-compatible leg.
# Same key as ANTHROPIC_*; the base is the OpenAI-compat surface (…/openai/v1).
OPENAI_API_KEY=op://common/anthropic/API_KEY
OPENAI_BASE_URL=https://unified-endpoint-main.app.iu-it.org/openai/v1

# The SAME key under the names config.yaml's `key_env` hints point at.
# `hermes model` / the provider setup wrote both into a plaintext ~/.hermes/.env
# via save_env_value() (hermes_cli/config.py — custom_endpoint_key_env() derives the
# name from the endpoint identity: `custom` → HERMES_CUSTOM_CUSTOM_API_KEY, the
# host → HERMES_CUSTOM_UNIFIED_ENDPOINT_MAIN_APP_IU_IT_ORG_API_KEY). The runtime
# resolves key_env through get_env_prefer_dotenv(): .env first, then the secret
# scope `secrets.command` populated — so declaring them here is what lets that
# .env not exist. Never run `hermes model` on the mini: it recreates the file.
HERMES_CUSTOM_CUSTOM_API_KEY=op://common/anthropic/API_KEY
HERMES_CUSTOM_UNIFIED_ENDPOINT_MAIN_APP_IU_IT_ORG_API_KEY=op://common/anthropic/API_KEY

# Anthropic — the approval classifier only (auxiliary.approval: claude-haiku-5-5-eu,
# native /anthropic leg). Every other auxiliary (compression, title_generation,
# vision) is on the IU OpenAI leg above; Google AI Studio direct (GEMINI_API_KEY)
# was retired 2026-09-13 — vision now runs gemini-3.5-flash through the same
# unified endpoint as everything else, no separate key.
ANTHROPIC_API_KEY=op://common/anthropic/API_KEY
ANTHROPIC_BASE_URL=op://common/anthropic/BASE_URL

# Tavily — web search, extract, crawl (replaces browser-based search)
TAVILY_API_KEY=op://hermes/tavily/API_KEY

# GitHub — issue creation, repo queries (watchdog, Phase 3)
GITHUB_TOKEN=op://hermes/github/token

# Argo API (formerly homelab API) — single integration layer for TickTick, Gmail,
# Calendar, Docker, UptimeKuma, Slack. Base URL: https://argo.jkrumm.com/api
# (env var name HOMELAB_API_KEY kept for shell/cron compatibility)
HOMELAB_API_KEY=op://common/api/SECRET

# KaraKeep (self-hosted read-later / bookmark "everything bucket", Tailscale-only at
# karakeep.jkrumm.com). Dedicated, independently-revocable API key for the karakeep
# skill — generate in KaraKeep UI (Settings → API Keys), store at op://hermes/karakeep.
# Base URL https://karakeep.jkrumm.com/api/v1 is hardcoded in the skill (like argo).
KARAKEEP_API_KEY=op://hermes/karakeep/api-key

# HyperDX/ClickStack (observability, Tailscale-only at hyperdx.jkrumm.com, on the
# VPS). Bearer for the `hyperdx` skill's MCP + REST v2 calls — a dedicated read-only
# HyperDX **user access key** (not the OTLP ingestion key), provisioned by
# `make hyperdx-agent-setup` in the vps repo. Base URL is hardcoded in the skill.
HYPERDX_AGENT_ACCESS_KEY=op://vps/clickstack/AGENT_ACCESS_KEY

# UptimeKuma push URLs — pinged on success by hermes-liveness.sh and hermes-backup.sh.
# Push monitors created manually in UK UI; URLs stored in 1Password after creation.
# UPTIME_PUSH_WATCHDOG has no pinger left (the out-of-band watchdog poller was retired).
UPTIME_PUSH_HERMES=op://hermes/uptime-kuma/agent-push-url
UPTIME_PUSH_BACKUP=op://hermes/uptime-kuma/backup-push-url
UPTIME_PUSH_WATCHDOG=op://hermes/uptime-kuma/watchdog-push-url

# Cron job idle timeout — hermes-agent/cron/scheduler.py kills any cron job that goes idle
# (no tool activity / agent thinking) for this long. Default 600s is too tight for the
# morning briefing's long-form German TTS run (the audio door chunks + synthesizes a
# multi-paragraph narrative); 1800s gives headroom.
HERMES_CRON_TIMEOUT=1800
