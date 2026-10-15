#!/bin/zsh
# Hermes backend server liveness ping — LLM-free.
#
# Probes `hermes serve` on loopback and pings its UptimeKuma push URL only on
# success. Every 5 min via com.jkrumm.hermes-serve-liveness; the paired monitor
# `Hermes Serve - Push` is 360s with maxretries 0.
#
# WHY IT ASSERTS THE AUTH GATE. `/api/status` is a public path — it answers before
# any credential is checked, because that is how a client DISCOVERS whether auth is
# required. So a serve that came up ungated answers 200 there and looks healthy,
# while exposing a socket that drives the agent. The response carries
# `auth_required`; this asserts it is true, and that an unauthenticated ws-ticket
# mint is refused.
#
# Every skip is logged — a silent `exit 0` is indistinguishable from a healthy run.

set -u

SECRETS_RUN="$HOME/.local/bin/secrets-run"
BASE="http://127.0.0.1:9119"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Skips go to stdout like hermes-liveness.sh, so a non-empty .err means a real script fault.
skip() { print "$(date '+%F %T') hermes-serve-liveness: $1 — no ping"; exit 0; }

[[ -x "$SECRETS_RUN" ]] || skip "$SECRETS_RUN missing"

PUSH_URL=$(timeout 10 "$SECRETS_RUN" read op://hermes/uptime-kuma/serve-push-url 2>/dev/null)
[[ -z "$PUSH_URL" ]] && skip "push url unresolvable"

STATUS=$(/usr/bin/curl -s --max-time 10 "$BASE/api/status" 2>/dev/null)
[[ -z "$STATUS" ]] && skip "/api/status not answering"

# `printf`, not `/usr/bin/echo` — there is no /usr/bin/echo on macOS; a wrong path
# here once made the pipeline fail silently while the script exited 0.
printf '%s' "$STATUS" | /opt/homebrew/bin/jq -e '.auth_required == true' >/dev/null 2>&1 \
  || skip "UNGATED — /api/status reports auth_required != true; the agent socket is open"

CODE=$(/usr/bin/curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "$BASE/api/auth/ws-ticket" 2>/dev/null)
[[ "$CODE" == "401" ]] || skip "unauthenticated ws-ticket mint returned $CODE, not 401"

/usr/bin/curl -fsS --max-time 10 "$PUSH_URL" >/dev/null
