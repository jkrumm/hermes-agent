#!/usr/bin/env bash
# Probes the live gateway: process, Slack + API server connected, API /health, local patches.
# Exit 0 = live and healthy. Read-only — safe to run any time (`make verify`).
set -uo pipefail
cd "$(dirname "$0")/.."

STATE="$HOME/.hermes/gateway_state.json"
fail=0
bad() { echo "  ✗ $1"; fail=1; }
ok() { echo "  ✓ $1"; }

if [[ ! -f "$STATE" ]]; then
  bad "no $STATE — gateway never started"
  exit 1
fi

pid=$(jq -r '.pid // 0' "$STATE")
state=$(jq -r '.gateway_state // ""' "$STATE")
slack=$(jq -r '.platforms.slack.state // ""' "$STATE")
api=$(jq -r '.platforms.api_server.state // ""' "$STATE")

if [[ "$state" == "running" ]] && kill -0 "$pid" 2>/dev/null; then ok "gateway running (pid alive)"; else bad "gateway_state=$state pid=$pid"; fi
if [[ "$slack" == "connected" ]]; then ok "slack connected"; else bad "slack=$slack"; fi
if [[ "$api" == "connected" ]]; then ok "api_server connected"; else bad "api_server=$api"; fi

host=$(timeout 10 "$HOME/.local/bin/secrets-run" read op://hermes/gateway/host 2>/dev/null || true)
if [[ -z "$host" ]]; then
  bad "gateway host did not resolve (secrets-run)"
else
  code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://$host:8642/health" || true)
  if [[ "$code" == "200" ]]; then ok "api /health 200"; else bad "api /health -> ${code:-no response}"; fi
fi

patches=$(make --no-print-directory patch-check 2>&1)
if grep -q '✗' <<<"$patches"; then bad "local patches"; echo "$patches"; else ok "local patches applied"; fi

exit "$fail"
