#!/bin/zsh
# Hermes liveness ping — LLM-free.
# Reads ~/.hermes/gateway_state.json, verifies gateway is running AND Slack is
# connected, then pings the UptimeKuma push URL on success. Run via cron every
# 5 min; UK monitor interval should be ~360s.
#
# Push URL is resolved on demand from op://hermes/uptime-kuma/agent-push-url via
# `secrets-run read` (the drop-in op shim — encrypted cache on the mini, biometric
# op on the MacBook). No plaintext ~/.hermes/.env dependency. If it can't be
# resolved, we skip the ping and UptimeKuma alerts on the missing heartbeat.

set -u

STATE="$HOME/.hermes/gateway_state.json"
SECRETS_RUN="$HOME/.local/bin/secrets-run"
# cron runs with a minimal PATH; prepend Homebrew so secrets-run finds sops+jq (its
# cache backend) and `timeout` resolves. Prepend (not replace) to preserve cron's PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ ! -f "$STATE" ]]; then
  exit 0  # No state file → no ping → UK alerts on missing heartbeat
fi

[[ -x "$SECRETS_RUN" ]] || exit 0

# `timeout` bounds a stuck backend (e.g. an unexpected prompt) so a 5-min cron can't
# hang and overlap. Failure → empty PUSH_URL → no ping → UK alerts on missing heartbeat.
PUSH_URL=$(timeout 10 "$SECRETS_RUN" read op://hermes/uptime-kuma/agent-push-url 2>/dev/null)
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
