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
#
# BOUNDED END TO END. launchd never starts a second instance of a running job, so one hung call
# would freeze this pusher and silence its monitor with nothing to restart it (dotfiles
# devhost-health, 2026-11-06, ~28 h). The LaunchAgent runs this under `jobrun --timeout 270`,
# and every external call carries its own limit (curl --max-time, `timeout`), so a hang fails
# THAT check and the monitor is told which one (skip → `status=down&msg=<reason>`).

set -u

SECRETS_RUN="$HOME/.local/bin/secrets-run"
BASE="${HERMES_SERVE_BASE:-http://127.0.0.1:9119}"  # override: tests only
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

PUSH_URL=""

# A withheld heartbeat names its reason: `status=down` with the message. Best effort and bounded;
# with no push URL (the resolve itself failed) the missing heartbeat is the alert.
push_down() {
  [[ -n "$PUSH_URL" ]] || return 0
  /usr/bin/curl -fsS --max-time 10 -G "${PUSH_URL%%\?*}" \
    --data-urlencode "status=down" --data-urlencode "msg=${1:0:200}" >/dev/null 2>&1 || true
}

# Skips go to stdout like hermes-liveness.sh, so a non-empty .err means a real script fault.
skip() { print "$(date '+%F %T') hermes-serve-liveness: $1 — monitor told down"; push_down "hermes-serve: $1"; exit 0; }

[[ -x "$SECRETS_RUN" ]] || skip "$SECRETS_RUN missing"

PUSH_URL=$(timeout 10 "$SECRETS_RUN" read op://hermes/uptime-kuma/serve-push-url 2>/dev/null)
[[ -z "$PUSH_URL" ]] && skip "push url unresolvable"

STATUS=$(/usr/bin/curl -s --max-time 10 "$BASE/api/status" 2>/dev/null)
[[ -z "$STATUS" ]] && skip "/api/status not answering"

# `printf`, not `/usr/bin/echo` — there is no /usr/bin/echo on macOS; a wrong path
# here once made the pipeline fail silently while the script exited 0.
printf '%s' "$STATUS" | timeout 5 /opt/homebrew/bin/jq -e '.auth_required == true' >/dev/null 2>&1 \
  || skip "UNGATED — /api/status reports auth_required != true; the agent socket is open"

CODE=$(/usr/bin/curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "$BASE/api/auth/ws-ticket" 2>/dev/null)
[[ "$CODE" == "401" ]] || skip "unauthenticated ws-ticket mint returned $CODE, not 401"

# The success push crosses Cloudflare to Kuma and fails transiently (curl rc 28 at 10 s, 502/530)
# while every check above has passed; 2026-11-14 06:47 and 06:52 UTC two consecutive runs failed
# that way and a single attempt turned each blip into a failed run. Three attempts, 5 s apart
# (worst case ~40 s, inside jobrun's 270 s); all three failing is a real fault, so the last
# curl's rc stays the job's rc and stderr keeps its reason. Same shape as hermes-liveness.sh.
for attempt in 1 2 3; do
  /usr/bin/curl -fsS --max-time 10 "$PUSH_URL" >/dev/null && exit 0
  PUSH_RC=$?
  /bin/echo "$(/bin/date -u +%Y-%m-%dT%H:%M:%SZ) success push attempt $attempt/3 failed (curl rc=$PUSH_RC)"
  (( attempt < 3 )) && sleep 5
done
exit "$PUSH_RC"
