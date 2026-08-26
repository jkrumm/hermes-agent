#!/bin/zsh
# Hermes backend server liveness ping — LLM-free.
#
# Probes `hermes serve` on loopback and pings its UptimeKuma push URL only on
# success. Every 5 min via com.jkrumm.hermes-serve-liveness; the paired monitor
# `Hermes Serve - Push` is 360s with maxretries 0.
#
# WHY IT ASSERTS THE AUTH GATE. `/api/status` is a public path — it answers before
# any credential is checked, because that is how a client DISCOVERS whether auth is
# required. So a serve that came up with its auth provider misconfigured answers
# 200 there and looks perfectly healthy, while exposing a socket that drives the
# agent to anything that can reach the port. The response carries `auth_required`;
# this asserts it is true. That check is the whole point of the heartbeat — the
# "is it listening" half is the easy part.

set -u

SECRETS_RUN="$HOME/.local/bin/secrets-run"
BASE="http://127.0.0.1:9119"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

[[ -x "$SECRETS_RUN" ]] || exit 0

PUSH_URL=$(timeout 10 "$SECRETS_RUN" read op://hermes/uptime-kuma/serve-push-url 2>/dev/null)
[[ -z "$PUSH_URL" ]] && exit 0   # unresolvable → no ping → UK alerts on the gap

STATUS=$(/usr/bin/curl -s --max-time 10 "$BASE/api/status" 2>/dev/null)
[[ -z "$STATUS" ]] && exit 0

# jq -e exits non-zero on false/null, so this is both the parse and the assertion.
/usr/bin/echo "$STATUS" | /opt/homebrew/bin/jq -e '.auth_required == true' >/dev/null 2>&1 || exit 0

/usr/bin/curl -fsS --max-time 10 "$PUSH_URL" >/dev/null
