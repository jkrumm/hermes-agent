#!/bin/zsh
# Hermes liveness ping — LLM-free.
# Reads ~/.hermes/gateway_state.json, verifies gateway is running AND Slack is
# connected, then pings the UptimeKuma push URL on success. Run via cron every
# 5 min; UK monitor interval should be ~360s.
#
# Push URL is sourced from ~/.hermes/.env (UPTIME_PUSH_HERMES). Resolved at
# `make hermes` time from op://hermes/uptime-kuma/agent-push-url.

set -u

STATE="$HOME/.hermes/gateway_state.json"
ENV_FILE="$HOME/.hermes/.env"

if [[ ! -f "$STATE" ]]; then
  exit 0  # No state file → no ping → UK alerts on missing heartbeat
fi

if [[ ! -f "$ENV_FILE" ]]; then
  exit 0
fi

PUSH_URL=$(grep -E '^UPTIME_PUSH_HERMES=' "$ENV_FILE" | cut -d= -f2-)
[[ -z "$PUSH_URL" ]] && exit 0

GATEWAY_STATE=$(/usr/bin/jq -r '.gateway_state // ""' "$STATE")
SLACK_STATE=$(/usr/bin/jq -r '.platforms.slack.state // ""' "$STATE")
PID=$(/usr/bin/jq -r '.pid // 0' "$STATE")

if [[ "$GATEWAY_STATE" != "running" ]]; then
  exit 0
fi

if [[ "$SLACK_STATE" != "connected" ]]; then
  exit 0
fi

if ! kill -0 "$PID" 2>/dev/null; then
  exit 0
fi

/usr/bin/curl -fsS --max-time 10 "$PUSH_URL" >/dev/null
