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

# Secrets are resolved by the gateway itself via config.yaml `secrets.command`
# (v0.19.0+). That source fails SOFT — a broken/incomplete cache yields a gateway
# that starts anyway and then can't authenticate. Total failure is already caught
# below (Slack won't be "connected"), but PARTIAL resolution — e.g. the Slack
# tokens render while HOMELAB_API_KEY doesn't — would otherwise ping a healthy
# heartbeat while every argo call 401s. Assert the cache renders every ref the
# template asks for; a shortfall skips the ping and UK alerts.
TPL="$HOME/.hermes/.env.tpl"
if [[ -f "$TPL" ]]; then
  WANT=$(/usr/bin/grep -cE '^[A-Za-z_][A-Za-z0-9_]*=' "$TPL")
  GOT=$(timeout 15 "$SECRETS_RUN" export --env-file="$TPL" 2>/dev/null | /usr/bin/grep -c '^export ')
  [[ -z "$GOT" || "$GOT" -lt "$WANT" ]] && exit 0
fi

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
