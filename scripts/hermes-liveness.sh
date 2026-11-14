#!/bin/zsh
# Hermes liveness ping — LLM-free.
# Reads ~/.hermes/gateway_state.json, verifies gateway is running AND the API server
# platform (:8642, Iris' surface) is connected AND the live pid is a descendant of launchd's ai.hermes.gateway job
# (an orphan gateway never keeps the monitor green) AND the agw inference gateway answers and
# accepts Hermes' door token (scripts/inference-gateway-check.sh), then pings the UptimeKuma
# push URL on success. Run every 5 min by
# the com.jkrumm.hermes-liveness LaunchAgent (launchd/, installed by `make setup`);
# UK monitor interval should be ~360s.
#
# Push URL is resolved on demand from op://hermes/uptime-kuma/agent-push-url via
# `secrets-run read` (the drop-in op shim — encrypted cache on the mini, biometric
# op on the MacBook). No plaintext ~/.hermes/.env dependency. If it can't be
# resolved, we skip the ping and UptimeKuma alerts on the missing heartbeat.
#
# BOUNDED END TO END. launchd never starts a second instance of a running job, so one hung
# call (secrets-run, launchctl, a probe) would freeze this pusher and silence its monitor for
# hours with nothing to restart it (dotfiles devhost-health, 2026-11-06, ~28 h). Two layers:
# the LaunchAgent runs the script under `jobrun --timeout 270` (a hard deadline under the 300 s
# cadence), and every external call below carries its own limit, so a hang fails THAT check
# and the monitor is told which one (skip → `status=down&msg=<reason>`).
#
# EVERY skip is logged. A silent `exit 0` is indistinguishable from a healthy
# tick in the log, so a guard that stops matching withholds the heartbeat
# invisibly — 2026-09-23, a one-hop pid check went stale with a plist rewrite
# and left a healthy gateway's monitor red for over an hour with an empty log.

set -u

STATE="$HOME/.hermes/gateway_state.json"
SECRETS_RUN="$HOME/.local/bin/secrets-run"
# launchd hands the job a minimal PATH (as cron did); prepend Homebrew so secrets-run
# finds sops+jq (its cache backend) and `timeout` resolves. Prepend, not replace.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# One external call may take this long (seconds). Env override exists for tests/hermes-liveness.
PROBE_TIMEOUT="${HERMES_LIVENESS_PROBE_TIMEOUT:-15}"
PUSH_URL=""

# A withheld heartbeat names its reason: `status=down` with the message, so Kuma shows WHY
# instead of waiting for the missing beat. Best effort and bounded; with no push URL
# (the resolve itself failed) the missing heartbeat is the alert, as before.
push_down() {
  [[ -n "$PUSH_URL" ]] || return 0
  /usr/bin/curl -fsS --max-time 10 -G "${PUSH_URL%%\?*}" \
    --data-urlencode "status=down" --data-urlencode "msg=${1:0:200}" >/dev/null 2>&1 || true
}

# stdout is the LaunchAgent's StandardOutPath (~/Library/Logs/hermes-liveness.log);
# stderr stays empty so a red monitor's `*.err` means a real script fault.
skip() {
  /bin/echo "$(/bin/date -u +%Y-%m-%dT%H:%M:%SZ) heartbeat skipped: ${1:-unknown} → monitor told down"
  push_down "${1:-unknown}"
  exit 0
}

if [[ ! -f "$STATE" ]]; then
  skip "no gateway_state.json at $STATE"
fi

[[ -x "$SECRETS_RUN" ]] || skip "$SECRETS_RUN is not executable"

# `timeout` bounds a stuck backend (e.g. an unexpected prompt) so a 5-min cron can't
# hang and overlap. Failure → empty PUSH_URL → no ping → UK alerts on missing heartbeat.
#
# Retried once, like the render below: the cache read is a sops decrypt, and a single transient
# miss (2026-11-09 03:07 and 03:13 UTC, cache untouched since the day before, the very next read
# fine) paged Kuma for a healthy gateway. The first failure's stderr is logged so a real fault
# names itself. With no URL the monitor cannot be told down, so the log says the missing beat is the alert.
PUSH_ERR=$(mktemp -t hermes-liveness) || PUSH_ERR=/dev/null
PUSH_URL=$(timeout 10 "$SECRETS_RUN" read op://hermes/uptime-kuma/agent-push-url 2>"$PUSH_ERR")
if [[ -z "$PUSH_URL" ]]; then
  sleep 3
  PUSH_URL=$(timeout 10 "$SECRETS_RUN" read op://hermes/uptime-kuma/agent-push-url 2>>"$PUSH_ERR")
fi
if [[ -z "$PUSH_URL" ]]; then
  ERR_TAIL=$(tail -c 200 "$PUSH_ERR" 2>/dev/null | tr '\n' ' ')
  rm -f "$PUSH_ERR"
  /bin/echo "$(/bin/date -u +%Y-%m-%dT%H:%M:%SZ) heartbeat skipped: push URL did not resolve (secrets-run read: ${ERR_TAIL:-no output, timed out or empty}) → no URL, Kuma's missing-heartbeat window is the alert"
  exit 0
fi
rm -f "$PUSH_ERR"

# Secrets are resolved by the gateway itself via config.yaml `secrets.command`
# (v0.19.0+). That source fails SOFT — a broken/incomplete cache yields a gateway
# that starts anyway and then can't authenticate. Total failure is already caught
# below (the API server won't be "connected"), but PARTIAL resolution — e.g. the API
# server key renders while HOMELAB_API_KEY doesn't — would otherwise ping a healthy
# heartbeat while every argo call 401s. Assert the cache renders every ref the
# template asks for; a shortfall skips the ping and UK alerts.
#
# Retried once: this decrypts every ref 288×/day, so a single transient failure
# (lock contention, a slow disk) must not suppress the heartbeat and page us for
# a healthy gateway. A real shortfall fails both attempts.
TPL="$HOME/.hermes/.env.tpl"
if [[ -f "$TPL" ]]; then
  WANT=$(/usr/bin/grep -cE '^[A-Za-z_][A-Za-z0-9_]*=' "$TPL")
  render_count() {
    timeout "$PROBE_TIMEOUT" "$SECRETS_RUN" export --env-file="$TPL" 2>/dev/null | /usr/bin/grep -c '^export '
  }
  GOT=$(render_count)
  if [[ -z "$GOT" || "$GOT" -lt "$WANT" ]]; then
    sleep 2
    GOT=$(render_count)
    [[ -z "$GOT" || "$GOT" -lt "$WANT" ]] && skip "secret cache renders ${GOT:-0} of $WANT refs (render failed or timed out)"
  fi
fi

GATEWAY_STATE=$(timeout 5 /usr/bin/jq -r '.gateway_state // ""' "$STATE")
API_STATE=$(timeout 5 /usr/bin/jq -r '.platforms.api_server.state // ""' "$STATE")
PID=$(timeout 5 /usr/bin/jq -r '.pid // 0' "$STATE")

# A restart (make deploy, hermes update) drains in-flight turns first — planned, not a failure
# (scripts/deploy.sh waits it out). Withhold the ping but do not push down: Kuma's own window
# still alerts if a drain never ends, while a normal restart no longer pages.
if [[ "$GATEWAY_STATE" == "draining" ]]; then
  /bin/echo "$(/bin/date -u +%Y-%m-%dT%H:%M:%SZ) heartbeat withheld: gateway_state=draining (planned restart, monitor not told down)"
  exit 0
fi

if [[ "$GATEWAY_STATE" != "running" ]]; then
  skip "gateway_state=$GATEWAY_STATE"
fi

if [[ "$API_STATE" != "connected" ]]; then
  skip "api_server=$API_STATE"
fi

if ! kill -0 "$PID" 2>/dev/null; then
  skip "state-file pid $PID is not alive"
fi

# The live PID must be the one launchd supervises. gateway_state.json is written
# by whichever gateway process last started — an orphan `hermes gateway run`
# (an ssh session, a stray manual start) would keep this monitor green while
# the supervised job sat dead or crash-looping. `launchctl print` is the only
# place launchd's own pid lives.
#
# Walk the WHOLE ancestry, never a fixed number of hops: the job wraps the
# gateway in helpers, and how many is upstream's business — stderr_timestamp
# always, plus `/usr/bin/osascript -e 'do shell script "exec …"'` since the
# macOS Local Network fix (hermes_cli/gateway_launchd.py, live here with the
# 2026-09-23 v0.21.4 update). A one-hop check (pid == job pid, else ppid == job
# pid) silently stopped matching the moment that wrapper appeared, and withheld
# the heartbeat for a perfectly healthy gateway.
LAUNCHD_PID=$(timeout 10 launchctl print "gui/$(id -u)/ai.hermes.gateway" 2>/dev/null | /usr/bin/sed -n 's/^[[:space:]]*pid = \([0-9]*\).*/\1/p' | head -1)
[[ -z "$LAUNCHD_PID" ]] && skip "launchctl reports no pid for ai.hermes.gateway"

SUPERVISED=0
WALK_PID="$PID"
for _ in {1..8}; do
  [[ "$WALK_PID" == "$LAUNCHD_PID" ]] && { SUPERVISED=1; break }
  [[ -z "$WALK_PID" || "$WALK_PID" == "0" || "$WALK_PID" == "1" ]] && break
  WALK_PID=$(timeout 5 ps -o ppid= -p "$WALK_PID" 2>/dev/null | tr -d ' ')
done
[[ "$SUPERVISED" == "1" ]] || skip "pid $PID is not a descendant of launchd job pid $LAUNCHD_PID (orphan gateway)"

# Every model call goes through the agw inference gateway (127.0.0.1:7794) with the `hermes=` door
# token. Hermes can be "running + API server connected" while the gateway is down or the token was
# rotated, and every turn then fails — so withhold the heartbeat. The check is a separate bash
# script run as a subprocess (shared with verify.sh / `make status`; no zsh-vs-bash sourcing); each
# curl inside it is --max-time bound (5 s + 10 s), well inside the 5-min tick.
# Up to 3 attempts, 8 s apart, so a gateway restart (deploy, KeepAlive) does not flip the monitor.
# Worst case ~90 s (3 x 25 s `timeout` + 2 x 8 s); the whole script stays under ~150 s, inside jobrun's 270 s.
GW_CHECK="${0:A:h}/inference-gateway-check.sh"
GW_OK=0
for attempt in 1 2 3; do
  # `timeout` is the script-level bound over the check's own curl limits (worst case 15 s inside).
  if GW_REASON=$(timeout 25 /bin/bash "$GW_CHECK" 2>&1); then GW_OK=1; break; fi
  (( attempt < 3 )) && sleep 8
done
if [[ "$GW_OK" != "1" ]]; then
  # The reason is the check's `fail ` lines, joined; a hung check (killed by `timeout`) prints none.
  GW_FAIL=$(print -r -- "$GW_REASON" | /usr/bin/sed -n 's/^fail //p' | paste -sd ';' - | /usr/bin/sed 's/;/; /g')
  skip "inference gateway: ${GW_FAIL:-check hung or gave no answer within 25 s}"
fi

# The success push crosses Cloudflare to Kuma and fails transiently: 2026-11-13 04:00, 05:00 and
# 17:00 UTC it returned 502/530 or timed out (rc 28) while every check above had passed, and
# the single attempt turned each blip into a failed run. Three attempts, 5 s apart (worst case
# ~40 s on top of the checks, inside jobrun's 270 s). All three failing means the check ran
# and the push was not delivered: exit 75 (EX_TEMPFAIL), which jobrun-grade reports as
# "undelivered" naming the push target, never as the job failing; the log keeps each curl rc.
for attempt in 1 2 3; do
  /usr/bin/curl -fsS --max-time 10 "$PUSH_URL" >/dev/null && exit 0
  PUSH_RC=$?
  /bin/echo "$(/bin/date -u +%Y-%m-%dT%H:%M:%SZ) success push attempt $attempt/3 failed (curl rc=$PUSH_RC)"
  (( attempt < 3 )) && sleep 5
done
exit 75
