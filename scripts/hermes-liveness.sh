#!/bin/zsh
# Hermes liveness ping — LLM-free.
# Reads ~/.hermes/gateway_state.json, verifies gateway is running AND Slack is
# connected AND the live pid is a descendant of launchd's ai.hermes.gateway job
# (an orphan gateway never keeps the monitor green), then pings the UptimeKuma
# push URL on success. Run every 5 min by
# the com.jkrumm.hermes-liveness LaunchAgent (launchd/, installed by `make setup`);
# UK monitor interval should be ~360s.
#
# Push URL is resolved on demand from op://hermes/uptime-kuma/agent-push-url via
# `secrets-run read` (the drop-in op shim — encrypted cache on the mini, biometric
# op on the MacBook). No plaintext ~/.hermes/.env dependency. If it can't be
# resolved, we skip the ping and UptimeKuma alerts on the missing heartbeat.
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

# stdout is the LaunchAgent's StandardOutPath (~/Library/Logs/hermes-liveness.log);
# stderr stays empty so a red monitor's `*.err` means a real script fault.
skip() {
  /bin/echo "$(/bin/date -u +%Y-%m-%dT%H:%M:%SZ) heartbeat skipped: ${1:-unknown} → UK alerts on the missing heartbeat"
  exit 0
}

if [[ ! -f "$STATE" ]]; then
  skip "no gateway_state.json at $STATE"
fi

[[ -x "$SECRETS_RUN" ]] || skip "$SECRETS_RUN is not executable"

# `timeout` bounds a stuck backend (e.g. an unexpected prompt) so a 5-min cron can't
# hang and overlap. Failure → empty PUSH_URL → no ping → UK alerts on missing heartbeat.
PUSH_URL=$(timeout 10 "$SECRETS_RUN" read op://hermes/uptime-kuma/agent-push-url 2>/dev/null)
[[ -z "$PUSH_URL" ]] && skip "push URL did not resolve (secrets-run read)"

# Secrets are resolved by the gateway itself via config.yaml `secrets.command`
# (v0.19.0+). That source fails SOFT — a broken/incomplete cache yields a gateway
# that starts anyway and then can't authenticate. Total failure is already caught
# below (Slack won't be "connected"), but PARTIAL resolution — e.g. the Slack
# tokens render while HOMELAB_API_KEY doesn't — would otherwise ping a healthy
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
    timeout 15 "$SECRETS_RUN" export --env-file="$TPL" 2>/dev/null | /usr/bin/grep -c '^export '
  }
  GOT=$(render_count)
  if [[ -z "$GOT" || "$GOT" -lt "$WANT" ]]; then
    sleep 2
    GOT=$(render_count)
    [[ -z "$GOT" || "$GOT" -lt "$WANT" ]] && skip "secret cache renders $GOT of $WANT refs"
  fi
fi

GATEWAY_STATE=$(/usr/bin/jq -r '.gateway_state // ""' "$STATE")
SLACK_STATE=$(/usr/bin/jq -r '.platforms.slack.state // ""' "$STATE")
PID=$(/usr/bin/jq -r '.pid // 0' "$STATE")

if [[ "$GATEWAY_STATE" != "running" ]]; then
  skip "gateway_state=$GATEWAY_STATE"
fi

if [[ "$SLACK_STATE" != "connected" ]]; then
  skip "slack=$SLACK_STATE"
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
LAUNCHD_PID=$(launchctl print "gui/$(id -u)/ai.hermes.gateway" 2>/dev/null | /usr/bin/sed -n 's/^[[:space:]]*pid = \([0-9]*\).*/\1/p' | head -1)
[[ -z "$LAUNCHD_PID" ]] && skip "launchctl reports no pid for ai.hermes.gateway"

SUPERVISED=0
WALK_PID="$PID"
for _ in {1..8}; do
  [[ "$WALK_PID" == "$LAUNCHD_PID" ]] && { SUPERVISED=1; break }
  [[ -z "$WALK_PID" || "$WALK_PID" == "0" || "$WALK_PID" == "1" ]] && break
  WALK_PID=$(ps -o ppid= -p "$WALK_PID" 2>/dev/null | tr -d ' ')
done
[[ "$SUPERVISED" == "1" ]] || skip "pid $PID is not a descendant of launchd job pid $LAUNCHD_PID (orphan gateway)"

/usr/bin/curl -fsS --max-time 10 "$PUSH_URL" >/dev/null
