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

# Every model call goes through the local inference gateway (agent-workflows, :7794),
# which mirrors IU's path layout: the OpenAI leg (brain, fallback, compression,
# title_generation) below, the Anthropic leg (vision, approval) further down.
OPENAI_BASE_URL=http://127.0.0.1:7794/openai/v1

# Not here: the gateway keys. The hermes door token (`hermes=` line of
# ~/.agent-workflows/data/door-tokens) opens the gateway, and `secrets.command` in
# config.yaml emits it as OPENAI_API_KEY, ANTHROPIC_API_KEY and the two `key_env`
# names, HERMES_CUSTOM_CUSTOM_API_KEY and
# HERMES_CUSTOM_UNIFIED_ENDPOINT_MAIN_APP_IU_IT_ORG_API_KEY. The runtime resolves
# key_env through get_env_prefer_dotenv(): .env first, then the secret scope
# `secrets.command` populated, so that .env need not exist. Never run `hermes model`
# on the mini: it recreates the file (custom_endpoint_key_env() derives those names).

# No `/v1`: the Anthropic SDK appends it.
ANTHROPIC_BASE_URL=http://127.0.0.1:7794/anthropic

# Tavily — web search, extract, crawl (replaces browser-based search)
TAVILY_API_KEY=op://hermes/tavily/API_KEY

# GitHub — issue creation, repo queries (watchdog, Phase 3)
GITHUB_TOKEN=op://hermes/github/token

# Software factory read API — the `factory read` CLI (fleet skill) takes this when FACTORY_TOKEN is
# absent. Read-only bearer: accepted on GET /v1/* only, IuRoot text redacted. Never the full
# FACTORY_TOKEN: Hermes takes voice and chat input and sends what it reads to models.
FACTORY_READ_TOKEN=op://mini/software-factory/FACTORY_READ_TOKEN

# Software factory signal token — `factory signal file --from owner:hermes` (fleet skill). Accepted on
# POST /signals only, as owner:hermes; 403 everywhere else, reads nothing. The fleet skill passes it as
# FACTORY_TOKEN for that one command. The owner's FACTORY_TOKEN never goes in this file.
FACTORY_SIGNAL_TOKEN=op://mini/software-factory/FACTORY_SIGNAL_TOKEN

# Argo API (formerly homelab API) — single integration layer for TickTick, Gmail,
# Calendar, Docker, UptimeKuma. Base URL: https://argo.jkrumm.com/api
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
