#!/usr/bin/env bash
# hermes-ops — the ONLY infrastructure-mutation interface the Hermes agent gets.
#
# WHY THIS EXISTS. Hermes hands a `terminal` tool to an LLM. Every ops command it
# composes is therefore free-form shell, which leaves exactly two bad options: let
# tirith/approvals gate each one (read-only triage stalls behind a Slack approval
# nobody answers at 05:00 — see skills/devops/homelab-alerts/SKILL.md "Approval
# Gate"), or allowlist shell shapes broadly (and the allowlist becomes the hole).
# A closed verb set breaks the trade: `hermes-ops.sh status` is a benign script
# call whether or not the LLM understood what it was doing, so Tier A can be
# allowlisted outright and Tier B stays mechanically bounded.
#
# The design rule that makes that true, and the one to defend in review: NO VERB
# ACCEPTS FREE-FORM SQL, A FREE-FORM COMMAND, OR A FREE-FORM URL. Every argument
# naming a host, container, stack, job or launchd label is checked against a fixed
# list or against the live container list before it reaches a remote command
# string. One free-form escape hatch and the whole exercise is theatre.
#
# TIERS
#   A  read-only. Safe to put in `command_allowlist` so triage never prompts.
#   B  mutating but idempotent and mechanical. Gated twice — this script needs
#      --confirm AND --why, independently of the Hermes approval layer. Without
#      --confirm every Tier B verb prints its plan and exits 0, changing nothing.
#
# Secrets resolve through `secrets-run`, the op shim (age-encrypted offline cache
# on this headless mini; live biometric op on the MacBook). A bare `op` here hangs
# on a prompt nobody can answer, which is why the backend marker is a hard gate.
#
# AUDIT LOG: ~/Library/Logs/hermes-ops.log, one line per invocation, always —
# including usage errors and dry runs. Register it with the existing
# com.jkrumm.log-rotate LaunchAgent by adding `hermes-ops.log` to the FILES array
# in dotfiles/scripts/log-rotate.sh (that list is DECLARED, never globbed, so an
# unregistered log is an unbounded log).
#
# TESTS: tests/test_hermes_ops.py (run with
# `~/.hermes/hermes-agent/venv/bin/python3 tests/test_hermes_ops.py`) covers the
# properties above — argument bounding, the closed verb set, Tier B's double
# gate, the --json contract, the audit log, the launchd-repair label allowlist,
# and the uk-sync -> env-check hard gate — against a stubbed ssh/curl/launchctl,
# never a real host. Re-run it after any edit here.

set -euo pipefail

# Hermes invokes this with a minimal environment. Prepend (not replace) Homebrew
# so `timeout`, `jq` and `secrets-run`'s own deps resolve — same reason
# hermes-liveness.sh does it.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

ARGO_BASE="https://argo.jkrumm.com/api"
# #alerts. A Slack channel id is not a secret (unlike a tailnet IP or a token) and
# hardcoding it is what keeps `alerts` from needing a free-form channel argument.
ALERTS_CHANNEL="C0AS1LAUQ3C"
REF_API_KEY="op://common/api/SECRET"

SECRETS_RUN="$HOME/.local/bin/secrets-run"
BACKEND_FILE="${SECRETS_BACKEND_FILE:-${XDG_CONFIG_HOME:-$HOME/.config}/secrets/backend}"
AUDIT_LOG="${HERMES_OPS_LOG:-$HOME/Library/Logs/hermes-ops.log}"

SECRET_TIMEOUT=15
HTTP_TIMEOUT=60
SSH_TIMEOUT=120
# sync-drift's local probe reaches GitHub over the network, so it is bounded like
# every remote call rather than left to git's own (absent) default.
GIT_TIMEOUT=60
# uk-sync walks every monitor over the network; the rest of Tier B is seconds.
DEPLOY_TIMEOUT=600

VALID_HOSTS=(homelab vps)

# Stack → the compose invocation it expands to. `make up` is deliberately NOT
# shelled: the homelab Makefile's targets are themselves `ssh homelab "..."`
# wrappers, so running `make up` inside an ssh session tries to ssh from the
# server back to itself. Verified with `make -n up`, which prints
# `ssh homelab "cd ~/homelab && op run ... docker compose up -d --remove-orphans"`.
# What follows is that expansion, run directly where it belongs.
#
# homelab-private is absent on purpose: its `make up` is not a compose up at all
# but scripts/vpn-cycle.sh — a full gluetun teardown plus exit-country validation
# plus a --no-cache torrent-app rebuild. That is a judgement call about the VPN
# kill switch, not a mechanical redeploy, and it does not belong in an unattended
# verb set.
#
# Space-separated strings, not arrays: macOS ships bash 3.2 only, which has no
# namerefs, so `VALID_STACKS_$host` cannot be dereferenced dynamically.
VALID_STACKS_homelab="homelab"
VALID_STACKS_vps="networking infra monitoring"

# The four `op run`-wrapped homelab host crons (crontab -l). All share
# ~/homelab/.env.tpl — which is why one dangling 1Password ref takes out all four
# at once, and why `env-check` exists.
VALID_CRONS=(vpn-watchdog auto-update garmin-auto-relogin koinsight-stats-push)

# LaunchAgents this repo's operator owns and that are safe to re-bootstrap after a
# macOS session teardown (smd boots agents out of gui/501 wholesale; see SKILL.md
# "Mac Mini session teardown"). ai.hermes.gateway is EXCLUDED: Hermes repairing
# the launchd job that hosts Hermes is a process killing itself mid-verb, and a
# gateway restart is a deliberate human action. com.iu.* are work agents, out of
# scope for this script.
VALID_LAUNCHD=(
  com.jkrumm.sideclaw
  com.jkrumm.linewatch-collector
  com.jkrumm.linewatch-heartbeat
  com.jkrumm.linewatch-watchdog
  com.jkrumm.devhost-health
  com.jkrumm.brain-sync
  com.jkrumm.brain-backup
  com.jkrumm.collie
  com.jkrumm.walkingpad
  com.jkrumm.usage-tracker
  com.jkrumm.log-rotate
  com.jkrumm.secrets-freshness
)

VALID_KUMA_PRESETS=(monitor-config heartbeats push-tokens created-dates)

# --- exit codes --------------------------------------------------------------
# 0 ok · 2 precondition failed · 3 remote failed · 64 usage error
EX_PRECONDITION=2
EX_REMOTE=3
EX_USAGE=64

# --- global flags ------------------------------------------------------------

JSON=0
CONFIRM=0
DRY_RUN=0
WHY=""

VERB=""
AUDIT_ARGS=""
AUDIT_TARGET="-"

# A --json error object cannot simply be printed where it is raised: most of them
# come from argo_get / ssh_run, which every verb calls inside `$( )`, and a
# subshell's stdout is captured by the assignment and thrown away. So the JSON
# error is staged here and flushed to real stdout by the EXIT trap in the parent,
# which is the one context guaranteed not to be inside a command substitution.
# (Human-mode errors go straight to stderr and never had this problem, which is
# exactly why it was invisible until --json was exercised on a failing call.)
ERR_JSON_FILE=$(mktemp -t hermes-ops 2>/dev/null || true)
START_EPOCH=$(date +%s)

# Set by any verb that has ALREADY written its own JSON object to stdout. The
# --json contract is one object per invocation; staging a second error object
# behind a payload that already carries `ok:false` turns the whole stream into a
# JSONDecodeError("Extra data") — for the agent parsing it mid-incident, that is
# strictly worse than no output at all. So the payload wins and _err falls back
# to stderr, which never pollutes stdout.
JSON_EMITTED=0

# --- audit -------------------------------------------------------------------

# Masks anything that looks like a credential before it reaches the log. The verb
# grammar admits no secrets (every argument is an enum, an integer, or a live
# container name), so this is a net for the mis-invocation — a pasted bearer token
# where a container name belongs — not the expected path.
#
# The test is length + mixed case + a digit, which is what a token looks like and
# what this fleet's identifiers do not: container names are lowercase-and-dashes,
# so `basalt-ui-marketing-basalt-ui-marketing-15` survives a length-only rule's
# false positive. op:// refs and env var NAMES are deliberately left readable —
# they are exactly what you need in the log to chase a dangling ref, and neither
# is a secret. Newlines collapse so one invocation stays one line.
redact() {
  local out="" w
  for w in ${1//$'\n'/ }; do
    if [ ${#w} -ge 24 ] && [[ "$w" == *[A-Z]* ]] && [[ "$w" == *[0-9]* ]] && [[ "$w" != *[/:]* ]]; then
      w="<redacted>"
    fi
    out="$out$w "
  done
  printf '%s' "${out% }"
}

audit() {
  local rc=$?
  local ts dur mode
  # Flush a staged --json error first: this is the only frame guaranteed to own
  # the real stdout. See ERR_JSON_FILE above.
  if [ -n "$ERR_JSON_FILE" ]; then
    [ -s "$ERR_JSON_FILE" ] && cat "$ERR_JSON_FILE"
    rm -f "$ERR_JSON_FILE"
  fi
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  dur=$(( $(date +%s) - START_EPOCH ))
  # An audit line that cannot distinguish "printed a plan" from "restarted the
  # container" is not an audit line. Tier A is `read` because it never mutates.
  if [ "$CONFIRM" = 1 ] && [ "$DRY_RUN" != 1 ]; then mode="confirmed"; else mode="dry-run"; fi
  case "$VERB" in
    uk-sync|restart-kuma|restart|redeploy|cron-rerun|devhost-health|launchd-repair) : ;;
    *) mode="read" ;;
  esac
  mkdir -p "$(dirname "$AUDIT_LOG")" 2>/dev/null || true
  printf '%s | verb=%s | mode=%s | args=%s | target=%s | rc=%s | dur=%ss | why=%s\n' \
    "$ts" "${VERB:--}" "$mode" "$(redact "${AUDIT_ARGS:--}")" "$AUDIT_TARGET" \
    "$rc" "$dur" "$(redact "${WHY:--}")" \
    >> "$AUDIT_LOG" 2>/dev/null || true
  exit "$rc"
}
trap audit EXIT

# --- errors ------------------------------------------------------------------

_err() {
  local code=$1; shift
  if [ "$JSON" = 1 ] && [ "$JSON_EMITTED" != 1 ] && [ -n "$ERR_JSON_FILE" ]; then
    MSG="$*" VERB="$VERB" CODE="$code" python3 -c '
import json, os
print(json.dumps({"verb": os.environ["VERB"] or None, "ok": False,
                  "exitCode": int(os.environ["CODE"]),
                  "error": os.environ["MSG"]}, indent=2))
' > "$ERR_JSON_FILE"
  else
    printf 'hermes-ops: %s\n' "$*" >&2
  fi
  exit "$code"
}

usage_err()  { _err "$EX_USAGE" "$@"; }
precond_err(){ _err "$EX_PRECONDITION" "$@"; }
remote_err() { _err "$EX_REMOTE" "$@"; }

need() { command -v "$1" >/dev/null 2>&1 || precond_err "missing required tool: $1"; }

in_list() {
  local needle=$1; shift
  local x
  for x in "$@"; do [ "$x" = "$needle" ] && return 0; done
  return 1
}

# --- preconditions -----------------------------------------------------------

# The marker tells us which secrets backend `secrets-run` will use, and that is
# the difference between "resolves from the sealed cache in 0.3s" and "blocks
# forever on a biometric prompt". `cache` is the mini, the machine Hermes runs on.
# `op` is a human's MacBook — allowed only with a TTY attached, because that is
# the only state in which someone can actually answer the prompt. Anything else
# fails fast rather than hanging a 5-minute cron. Same signal remote-dev.sh keys
# off, read the same way.
require_backend() {
  local backend
  backend=$(cat "$BACKEND_FILE" 2>/dev/null || true)
  case "$backend" in
    cache) : ;;
    op)
      [ -t 0 ] || precond_err "secrets backend is 'op' and there is no TTY — a biometric prompt would hang here. Run this on the Mac mini (backend 'cache') or from an interactive shell."
      ;;
    *)
      precond_err "no secrets backend marker at $BACKEND_FILE — refusing to run rather than hang on an interactive 'op' prompt. This script belongs on the Mac mini."
      ;;
  esac
  [ -x "$SECRETS_RUN" ] || precond_err "secrets-run not found at $SECRETS_RUN"
}

API_KEY=""
load_api_key() {
  [ -n "$API_KEY" ] && return 0
  require_backend
  need timeout
  API_KEY=$(timeout "$SECRET_TIMEOUT" "$SECRETS_RUN" read "$REF_API_KEY" 2>/dev/null) \
    || precond_err "could not resolve $REF_API_KEY via secrets-run"
  [ -n "$API_KEY" ] || precond_err "$REF_API_KEY resolved empty"
}

# --- transport ---------------------------------------------------------------

# The bearer goes in via `curl -K -` (config on stdin), never argv — a key in a
# command line is readable from `ps` by anything running as this user, and this
# machine runs untrusted-ish agent workloads by design.
argo_get() {
  local path=$1 out status body
  load_api_key
  need curl
  out=$(printf 'header = "Authorization: Bearer %s"\n' "$API_KEY" \
    | timeout "$HTTP_TIMEOUT" curl -sS -K - -w '\n%{http_code}' \
        --connect-timeout 5 --max-time "$HTTP_TIMEOUT" "${ARGO_BASE}${path}") \
    || remote_err "argo request failed (network/timeout): $path"
  status="${out##*$'\n'}"
  body="${out%$'\n'"${status}"}"
  [ "$status" = "200" ] || remote_err "argo $path returned HTTP $status"
  printf '%s' "$body"
}

# Read-only ssh. BatchMode so a missing key fails instead of prompting; timeout so
# a half-open tailnet connection cannot wedge a cron.
ssh_run() {
  local host=$1 cmd=$2 to=${3:-$SSH_TIMEOUT}
  need timeout
  # shellcheck disable=SC2029  # remote-side expansion is the intent ($HOME differs)
  timeout "$to" ssh -o BatchMode=yes -o ConnectTimeout=10 "$host" "$cmd"
}

# --- validation --------------------------------------------------------------

valid_host() {
  in_list "$1" "${VALID_HOSTS[@]}" \
    || usage_err "unknown host: $1 (must be one of: ${VALID_HOSTS[*]})"
}

valid_int() {
  case "$2" in
    ''|*[!0-9]*) usage_err "$1 must be a non-negative integer (got: $2)" ;;
  esac
}

# Two gates, deliberately. The shape check rejects anything that could not be a
# container name before it is ever put in a URL; the live-list check is what makes
# `restart` and `logs` incapable of naming something that does not exist.
valid_container() {
  local host=$1 name=$2 body
  case "$name" in
    ''|*[!A-Za-z0-9_.-]*) usage_err "not a container name: $name" ;;
  esac
  body=$(argo_get "/docker/${host}/containers")
  NAME="$name" python3 -c '
import json, os, sys
names = [c.get("name") for c in json.loads(sys.stdin.read())]
if os.environ["NAME"] not in names:
    sys.stderr.write("known containers: " + ", ".join(sorted(n for n in names if n)) + "\n")
    sys.exit(1)
' <<<"$body" || usage_err "no container named '$name' on $host (see list above)"
}

# --- Tier B gating -----------------------------------------------------------

require_why() {
  [ -n "$WHY" ] || usage_err "Tier B verbs require --why \"<reason>\" (it is what lands in the audit log)"
}

PLAN=()
# Step results of the last executed plan, as flat (command, rc, output) triples.
PLAN_RESULTS=()
# uk-sync has to fold its before/after down-counts into the SAME object as the
# step results — two objects would break the --json contract. With this set,
# run_plan executes and records but leaves the emitting to the caller.
PLAN_DEFER_JSON=0

# Prints the plan and stops, unless --confirm was given AND --dry-run was not.
# Default-deny: a Tier B verb invoked with no flags is a dry run, on purpose.
run_plan() {
  local i out rc
  if [ "$CONFIRM" != 1 ] || [ "$DRY_RUN" = 1 ]; then
    if [ "$JSON" = 1 ]; then
      printf '%s\0' "${PLAN[@]}" | VERB="$VERB" TARGET="$AUDIT_TARGET" WHY="$WHY" python3 -c '
import json, os, sys
cmds = [c.decode() for c in sys.stdin.buffer.read().split(b"\0")[:-1]]
print(json.dumps({"verb": os.environ["VERB"], "ok": True, "tier": "B",
                  "dryRun": True, "confirmed": False,
                  "target": os.environ["TARGET"], "why": os.environ["WHY"] or None,
                  "commands": cmds,
                  "note": "nothing ran — re-invoke with --confirm --why \"<reason>\" to execute"},
                 indent=2))
'
    else
      printf 'DRY RUN — nothing executed.\n\n'
      for i in "${PLAN[@]}"; do printf '  %s\n' "$i"; done
      printf '\nRe-invoke with --confirm --why "<reason>" to execute.\n'
    fi
    return 0
  fi

  local results=()
  for i in "${PLAN[@]}"; do
    [ "$JSON" = 1 ] || printf '==> %s\n' "$i"
    set +e
    out=$(eval "$i" 2>&1)
    rc=$?
    set -e
    results+=("$i" "$rc" "$out")
    if [ "$JSON" != 1 ]; then
      [ -n "$out" ] && printf '%s\n' "$out"
      printf '    rc=%s\n' "$rc"
    fi
    PLAN_RESULTS=("${results[@]}")
    [ "$rc" -eq 0 ] || {
      # A failed step is reported through the same object shape as a successful
      # one (ok:false), and JSON_EMITTED then keeps remote_err from appending a
      # second object behind it.
      if [ "$JSON" = 1 ]; then
        printf '%s\0' "${results[@]}" | emit_plan_results 1
        JSON_EMITTED=1
      fi
      remote_err "step failed (rc=$rc): $i"
    }
  done
  if [ "$JSON" = 1 ] && [ "$PLAN_DEFER_JSON" != 1 ]; then
    printf '%s\0' "${PLAN_RESULTS[@]}" | emit_plan_results 0
    JSON_EMITTED=1
  fi
  return 0
}

# $1: "0" when every step succeeded. $2: optional JSON object merged into the
# result — how a verb adds its own verification fields without a second object.
emit_plan_results() {
  OK="$1" EXTRA="${2:-}" VERB="$VERB" TARGET="$AUDIT_TARGET" WHY="$WHY" python3 -c '
import json, os, sys
parts = [p.decode() for p in sys.stdin.buffer.read().split(b"\0")[:-1]]
steps = [{"command": parts[i], "rc": int(parts[i+1]), "output": parts[i+2]}
         for i in range(0, len(parts), 3)]
out = {"verb": os.environ["VERB"], "ok": os.environ["OK"] == "0",
       "tier": "B", "dryRun": False, "confirmed": True,
       "target": os.environ["TARGET"], "why": os.environ["WHY"] or None,
       "steps": steps}
if os.environ["EXTRA"]:
    out.update(json.loads(os.environ["EXTRA"]))
print(json.dumps(out, indent=2))
'
}

# =============================================================================
# TIER A — read-only
# =============================================================================

cmd_status() {
  AUDIT_TARGET="argo"
  local summary status
  summary=$(argo_get "/summary")
  status=$(argo_get "/uptime-kuma/status")

  JSON="$JSON" python3 - "$summary" "$status" <<'PY'
import json, os, sys
summary, status = json.loads(sys.argv[1]), json.loads(sys.argv[2])
uk = summary.get("uptimeKuma", {})
down = status.get("down", 0)
data = {
    "verb": "status", "ok": True, "tier": "A",
    # /uptime-kuma/status counts LEAF monitors only. Group monitors cascade to
    # down whenever any child fails, so a status==0 filter over /monitors
    # reports a dozen failures for three real ones. This is the honest number.
    "leafDown": down, "leafUp": status.get("up"), "leafTotal": status.get("total"),
    "kumaState": status.get("status"), "kumaLastError": status.get("lastError"),
    "kumaStaleSince": status.get("staleSince"),
    "downMonitors": uk.get("downMonitors", []),
    "dockerHomelab": summary.get("dockerHomelab", {}).get("counts")
                     or summary.get("dockerHomelab", {}).get("error"),
    "dockerVps": summary.get("dockerVps", {}).get("counts")
                 or summary.get("dockerVps", {}).get("error"),
    "generatedAt": summary.get("generatedAt"),
}
if os.environ["JSON"] == "1":
    print(json.dumps(data, indent=2)); sys.exit()

print(f"uptime-kuma   {data['leafUp']}/{data['leafTotal']} up   down={down} (leaf monitors only)")
print(f"              state={data['kumaState']}  lastError={data['kumaLastError'] or '-'}")
if data["downMonitors"]:
    print("\ndown:")
    for m in data["downMonitors"]:
        print("  " + (m if isinstance(m, str) else json.dumps(m)))
print()
for host in ("dockerHomelab", "dockerVps"):
    v = data[host]
    print(f"docker {host[6:].lower():<8} {v if isinstance(v, str) else json.dumps(v)}")
print("\nGroup monitors are excluded: they cascade from their children and inflate")
print("the count. Use `monitors` to see group state.")
PY
}

cmd_monitors() {
  AUDIT_TARGET="argo"
  local filter="${1:-}"
  local body
  body=$(argo_get "/uptime-kuma/monitors")
  JSON="$JSON" FILTER="$filter" python3 - "$body" <<'PY'
import json, os, sys
ms = json.loads(sys.argv[1]).get("monitors", [])
f = os.environ["FILTER"].lower()
if f:
    ms = [m for m in ms if f in (m.get("name") or "").lower()]
STATUS = {1: "UP", 0: "DOWN", 2: "PENDING", 3: "MAINT"}
for m in ms:
    m["statusText"] = STATUS.get(m.get("status"), str(m.get("status")))
if os.environ["JSON"] == "1":
    print(json.dumps({"verb": "monitors", "ok": True, "tier": "A",
                      "filter": os.environ["FILTER"] or None,
                      "count": len(ms), "monitors": ms}, indent=2))
    sys.exit()
if not ms:
    print("(no monitors matched)"); sys.exit()
print(f"{'id':>4}  {'status':<8} {'type':<8} {'1d':>7} {'30d':>7}  name")
for m in sorted(ms, key=lambda x: int(x.get("id", 0))):
    # uptime1d dates a corruption without touching the DB: a fresh outage sits
    # near 0.0x, a monitor broken since yesterday's bad sync sits near 0.5.
    print(f"{m.get('id',''):>4}  {m['statusText']:<8} {m.get('type',''):<8} "
          f"{(m.get('uptime1d') or 0):>7.3f} {(m.get('uptime30d') or 0):>7.3f}  {m.get('name','')}")
print(f"\n{len(ms)} monitor(s). type=group entries cascade from children — symptoms, not incidents.")
PY
}

cmd_containers() {
  local host="${1:-}"
  [ -n "$host" ] || usage_err "usage: hermes-ops.sh containers <homelab|vps> [--json]"
  valid_host "$host"
  AUDIT_TARGET="$host"
  local body
  body=$(argo_get "/docker/${host}/containers")
  JSON="$JSON" HOST="$host" python3 - "$body" <<'PY'
import json, os, sys
cs = json.loads(sys.argv[1])
if os.environ["JSON"] == "1":
    print(json.dumps({"verb": "containers", "ok": True, "tier": "A",
                      "host": os.environ["HOST"], "count": len(cs),
                      "containers": cs}, indent=2))
    sys.exit()
print(f"{'state':<10} {'health':<10} {'restarts':>8}  name")
for c in sorted(cs, key=lambda x: x.get("name") or ""):
    print(f"{c.get('state',''):<10} {(c.get('health') or '-'):<10} "
          f"{c.get('restartCount',0):>8}  {c.get('name','')}")
print(f"\n{len(cs)} container(s) on {os.environ['HOST']}")
PY
}

cmd_logs() {
  local host="${1:-}" container="${2:-}" tail="${3:-200}"
  [ -n "$host" ] && [ -n "$container" ] \
    || usage_err "usage: hermes-ops.sh logs <homelab|vps> <container> [lines] [--json]"
  valid_host "$host"
  valid_int "lines" "$tail"
  # Default 200, not argo's 50: the first [ERROR] of a dangling-ref break sat at
  # line 131 of 200 in the 2026-08-01 incident, and the OK→ERROR transition is
  # the whole diagnosis. A 50-line window shows only the aftermath.
  valid_container "$host" "$container"
  AUDIT_TARGET="${host}/${container}"
  local body
  body=$(argo_get "/docker/${host}/logs/${container}?tail=${tail}")
  JSON="$JSON" python3 - "$body" <<'PY'
import json, os, sys
d = json.loads(sys.argv[1])
if os.environ["JSON"] == "1":
    d.update({"verb": "logs", "ok": True, "tier": "A"})
    print(json.dumps(d, indent=2)); sys.exit()
for line in d.get("lines", []):
    print(line)
PY
}

cmd_alerts() {
  local n="${1:-40}"
  valid_int "count" "$n"
  AUDIT_TARGET="slack/${ALERTS_CHANNEL}"
  local body
  body=$(argo_get "/slack/channels/${ALERTS_CHANNEL}/messages?limit=${n}")
  JSON="$JSON" python3 - "$body" <<'PY'
import datetime as dt, json, os, sys
d = json.loads(sys.argv[1])
msgs = d.get("messages", [])
if os.environ["JSON"] == "1":
    print(json.dumps({"verb": "alerts", "ok": True, "tier": "A",
                      "count": len(msgs), "hasMore": d.get("has_more"),
                      "messages": msgs}, indent=2))
    sys.exit()
for m in msgs:
    ts = dt.datetime.fromtimestamp(float(m["ts"]), dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print(f"{ts}  {(m.get('text') or '').splitlines()[0][:160]}")
print(f"\n{len(msgs)} message(s), newest first. Timestamps are UTC; uptime-kuma "
      "container logs are +02:00 — convert before correlating.")
PY
}

# Directly detects the root cause of the 2026-08-01 outage: `op run` fails
# WHOLESALE when any single reference in the shared .env.tpl cannot be resolved.
# One 1Password item renamed or retired takes out all four homelab crons at once
# (vpn-watchdog every 5 min, auto-update, garmin-relogin, koinsight-stats-push)
# and re-corrupts uptime-kuma on the next sync. Nothing else in this fleet checks
# it — the symptom that pages you is a missing heartbeat three layers downstream.
cmd_env_check() {
  AUDIT_TARGET="homelab,vps"
  local hl_out hl_rc vps_out vps_rc
  set +e
  hl_out=$(ssh_run homelab 'cd ~/homelab && op run --env-file=.env.tpl -- true' 2>&1); hl_rc=$?
  vps_out=$(ssh_run vps 'cd ~/vps && op run --env-file=.env.tpl -- true' 2>&1); vps_rc=$?
  set -e

  local rc
  set +e
  JSON="$JSON" python3 - "$hl_out" "$hl_rc" "$vps_out" "$vps_rc" <<'PY'
import json, os, re, sys

def parse(out, rc):
    # `op run` prints "could not resolve item UUID for item <name>: could not
    # find item <name> in vault <id>" — the item name is the actionable half.
    # The vault UUID is deliberately not extracted; it never needs to be logged.
    refs = set(re.findall(r"could not find item ([^\s]+) in vault", out))
    refs |= set(re.findall(r"could not resolve item UUID for item ([^:\s]+)", out))
    return {"ok": rc == 0, "exitCode": rc,
            "danglingItems": sorted(refs),
            "error": None if rc == 0 else out.strip()[:2000]}

hl = parse(sys.argv[1], int(sys.argv[2]))
vps = parse(sys.argv[3], int(sys.argv[4]))
ok = hl["ok"] and vps["ok"]
if os.environ["JSON"] == "1":
    print(json.dumps({"verb": "env-check", "ok": ok, "tier": "A",
                      "homelab": hl, "vps": vps}, indent=2))
else:
    for name, r in (("homelab ~/homelab/.env.tpl", hl), ("vps     ~/vps/.env.tpl", vps)):
        verdict = "OK" if r["ok"] else "FAILED"
        print(f"{name:<28} {verdict} (rc={r['exitCode']})")
        for item in r["danglingItems"]:
            print(f"  dangling 1Password item: {item}")
        if r["error"]:
            print("  " + r["error"].replace("\n", "\n  "))
    if not ok:
        print("\nop run fails wholesale on ONE unresolvable ref. Every cron sharing this")
        print("template is down until the item is restored or the ref removed — and")
        print("uk-sync would write empty values into uptime-kuma. Fix this first.")
sys.exit(0 if ok else 3)
PY
  rc=$?
  set -e
  # No remote_err here on purpose. The object above already carries ok:false, the
  # per-server exit codes and the dangling item names; raising an error would
  # print a SECOND JSON object and hand the caller an unparseable stdout at the
  # exact moment it is triaging. The exit code is the only thing left to carry.
  return "$rc"
}

# One probe, run identically against the mini clone and the server clone. It
# writes NOTHING: `git ls-remote` asks origin for its master sha over the network
# without touching a single local ref, where the `git fetch` this used to run
# rewrote the clone's remote-tracking refs. Tier A is the tier that gets
# allowlisted for unattended triage, so "read-only" has to be literally true
# rather than nearly true.
#
# The cost of dropping the fetch, and the reason `inSync` exists: `behindOrigin`
# can only be enumerated from objects the clone ALREADY has, so it is empty or
# unavailable exactly when the clone is furthest behind. `inSync` — live origin
# sha vs HEAD — is the authoritative verdict and never depends on cached state.
# Read that field, not the length of the commit list.
drift_probe_cmd() {
  # shellcheck disable=SC2016  # $O is expanded by the shell that RUNS the probe
  # (bash -c here, the server's shell over ssh), never by this one — the single
  # quotes are the point, and $1 is the only value this side interpolates.
  printf 'export GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10"; cd %s && O=$(git ls-remote origin master) && [ -n "$O" ] && O=${O%%%%[!0-9a-f]*} && git status -sb && echo "--- head ---" && git rev-parse HEAD && echo "--- origin ---" && echo "$O" && echo "--- behind ---" && { git cat-file -e "$O^{commit}" 2>/dev/null && git log "HEAD..$O" --oneline || echo "(behind-enumeration-unavailable)"; }' "$1"
}

# The mini's clone is NOT deployed truth. The servers deploy by `git pull` from
# origin, so origin/master is what runs and the local clone is an opinion. A 2026
# incident concluded "this monitor is not declared anywhere" from a local clone
# that was two commits behind the origin that declared it. The output labels the
# two sides differently for exactly that reason.
#
# Every probe's exit code is carried through to a per-entry `ok`, and one failure
# fails the whole verb (exit 3). An unreachable server used to surface as an
# entry with an empty behindOrigin and a top-level ok:true — i.e. as a clean,
# in-sync clone. That is the same wrong-conclusion failure this verb exists to
# prevent, restated one level up: "I could not look" must never render as
# "nothing to see".
cmd_sync_drift() {
  AUDIT_TARGET="homelab,vps"
  # The local probe reaches the network before any ssh_run does its own check.
  need timeout
  local -a rows=()
  local repo local_path host remote_path out rc prc

  for spec in \
    "homelab|$HOME/SourceRoot/homelab|homelab|~/homelab" \
    "homelab-private|$HOME/SourceRoot/homelab-private|homelab|~/homelab-private" \
    "vps|$HOME/SourceRoot/vps|vps|~/vps"
  do
    IFS='|' read -r repo local_path host remote_path <<<"$spec"

    if [ -d "$local_path/.git" ]; then
      set +e
      out=$(timeout "$GIT_TIMEOUT" bash -c "$(drift_probe_cmd "$local_path")" 2>&1); rc=$?
      set -e
    else
      out="(no clone at $local_path)"
      rc=$EX_PRECONDITION
    fi
    rows+=("$repo" "mini" "$local_path" "$rc" "$out")

    set +e
    out=$(ssh_run "$host" "$(drift_probe_cmd "$remote_path")" 2>&1); rc=$?
    set -e
    rows+=("$repo" "$host" "$remote_path" "$rc" "$out")
  done

  set +e
  printf '%s\0' "${rows[@]}" | JSON="$JSON" python3 -c '
import json, os, sys
p = [x.decode() for x in sys.stdin.buffer.read().split(b"\0")[:-1]]
UNAVAILABLE = "(behind-enumeration-unavailable)"
entries = []
for i in range(0, len(p), 5):
    repo, side, path, rc, out = p[i:i+5]
    rc = int(rc)
    sec, cur = {"status": [], "head": [], "origin": [], "behind": []}, "status"
    for line in out.splitlines():
        key = {"--- head ---": "head", "--- origin ---": "origin",
               "--- behind ---": "behind"}.get(line)
        if key:
            cur = key
        else:
            sec[cur].append(line)

    def first(k):
        vals = [l.strip() for l in sec[k] if l.strip()]
        return vals[0] if vals else None

    head_sha, origin_sha = first("head"), first("origin")
    # A probe that exited non-zero, or that came back without both shas, did not
    # answer the question. It is reported as unanswered, never as in sync.
    ok = rc == 0 and bool(head_sha) and bool(origin_sha)
    behind = [l for l in sec["behind"] if l.strip()]
    if not ok:
        behind, source = None, None
    elif UNAVAILABLE in behind:
        behind, source = None, "unavailable"
    else:
        source = "cached-refs"
    entries.append({
        "repo": repo, "side": side, "deployedTruth": side != "mini",
        "path": path, "ok": ok, "exitCode": rc,
        "branch": first("status"),
        "headSha": head_sha, "originSha": origin_sha,
        "inSync": (head_sha == origin_sha) if ok else None,
        "behindOrigin": behind, "behindOriginSource": source,
        "error": None if ok else (out.strip()[:2000] or "probe returned no output"),
        "raw": out,
    })

all_ok = all(e["ok"] for e in entries)
if os.environ["JSON"] == "1":
    print(json.dumps({
        "verb": "sync-drift", "ok": all_ok, "tier": "A",
        "note": "side=mini is a local working copy, NOT what runs. The servers "
                "deploy by git pull from origin, so only deployedTruth=true "
                "entries describe running config. Read inSync for the verdict: "
                "ok=false means the clone could not be reached (behindOrigin is "
                "null, NOT empty), and behindOriginSource=unavailable means the "
                "commit list could not be enumerated from cached refs even "
                "though inSync is authoritative.",
        "clones": entries}, indent=2))
    sys.exit(0 if all_ok else 3)

for e in entries:
    repo, side, path, rc = e["repo"], e["side"], e["path"], e["exitCode"]
    tag = "DEPLOYED TRUTH" if e["deployedTruth"] else "local copy, NOT deployed"
    if not e["ok"]:
        tag += " - UNREACHABLE"
    print(f"{repo:<16} {side:<9} {path:<44} [{tag}]")
    if not e["ok"]:
        print(f"  UNREACHABLE (rc={rc}) - drift is UNKNOWN, not clean")
        for line in (e["error"] or "").splitlines():
            print(f"    {line}")
        print()
        continue
    branch, head, origin = e["branch"], e["headSha"], e["originSha"]
    verdict = "IN SYNC" if e["inSync"] else "DRIFTED"
    print(f"  {branch}")
    print(f"  HEAD {head[:12]}  origin {origin[:12]}  {verdict}")
    if e["behindOriginSource"] == "unavailable":
        print("  behind: (not enumerable — this clone has no fetched objects for "
              "the origin commit; the sha comparison above is the verdict)")
    for line in e["behindOrigin"] or []:
        print(f"  behind: {line}")
    print()
print("Only the server rows describe what is running. A clean mini clone proves nothing.")
if not all_ok:
    print("\nAt least one clone could not be probed. Treat its drift as unknown.")
sys.exit(0 if all_ok else 3)
'
  prc=$?
  set -e
  # The object above already reports which clone failed and why; a second error
  # object would break the --json contract, so only the exit code is left to
  # carry (3 = a clone could not be probed).
  return "$prc"
}

# Fixed presets, one hardcoded query each. No SQL argument is accepted, and the
# only parameter any preset takes is an integer monitor id.
cmd_kuma_db() {
  local preset="${1:-}"
  [ -n "$preset" ] || usage_err "usage: hermes-ops.sh kuma-db <${VALID_KUMA_PRESETS[*]}> [args] [--json]"
  in_list "$preset" "${VALID_KUMA_PRESETS[@]}" \
    || usage_err "unknown kuma-db preset: $preset (must be one of: ${VALID_KUMA_PRESETS[*]})"
  AUDIT_TARGET="homelab/uptime-kuma"

  local sql
  case "$preset" in
    monitor-config)
      # Empty hostname / http://:port/ URLs are the sync.py env-var corruption
      # fingerprint — an unset ${VAR} substituted as "" and written back.
      sql="SELECT id, name, type, active, url, hostname, port FROM monitor WHERE type IN ('http','keyword') ORDER BY id;"
      ;;
    heartbeats)
      local id="${2:-}"
      [ -n "$id" ] || usage_err "usage: hermes-ops.sh kuma-db heartbeats <monitorId>"
      valid_int "monitorId" "$id"
      AUDIT_TARGET="homelab/uptime-kuma#${id}"
      # heartbeat.time is an ISO-8601 STRING, not unixepoch. status: 1 up, 2
      # pending, 0 down. The last 1 → first 0/2 transition dates the breakage.
      sql="SELECT monitor_id, time, status, msg FROM heartbeat WHERE monitor_id = ${id} ORDER BY time DESC LIMIT 25;"
      ;;
    push-tokens)
      # The token IS the credential — the push URL built from it can write
      # heartbeats. Only a 4-char prefix is selected, which is enough to match a
      # monitor against a local ~/.config/uptime-kuma/*-push-url file without
      # ever moving the secret into a log or a Slack message.
      sql="SELECT id, name, active, interval, substr(push_token,1,4) || '...' AS token_prefix FROM monitor WHERE type = 'push' ORDER BY id;"
      ;;
    created-dates)
      # created_date is UTC. A monitor created in the same second as a sync burst
      # was added by hand mid-incident — a strong hint its pusher was never wired.
      sql="SELECT id, name, type, active, created_date FROM monitor ORDER BY created_date DESC LIMIT 30;"
      ;;
  esac

  local out rc
  set +e
  out=$(ssh_run homelab "docker exec uptime-kuma sqlite3 -header -column /app/data/kuma.db \"${sql}\"" 2>&1); rc=$?
  set -e
  [ "$rc" -eq 0 ] || remote_err "kuma-db $preset failed (rc=$rc): $out"

  if [ "$JSON" = 1 ]; then
    OUT="$out" PRESET="$preset" SQL="$sql" python3 -c '
import json, os
print(json.dumps({"verb": "kuma-db", "ok": True, "tier": "A",
                  "preset": os.environ["PRESET"], "query": os.environ["SQL"],
                  "rows": os.environ["OUT"]}, indent=2))
'
  else
    printf '%s\n' "$out"
  fi
}

# A push monitor at 0 over BOTH windows has never received a single heartbeat —
# nobody built the pusher. A transient gap keeps uptime30d high, so this cleanly
# separates "orphaned monitor" from "agent had a bad night".
cmd_heartbeat_gaps() {
  AUDIT_TARGET="argo"
  local body
  body=$(argo_get "/uptime-kuma/monitors")
  JSON="$JSON" python3 - "$body" <<'PY'
import json, os, sys
ms = json.loads(sys.argv[1]).get("monitors", [])
orphans = [m for m in ms
           if m.get("type") == "push"
           and not (m.get("uptime1d") or 0) and not (m.get("uptime30d") or 0)]
if os.environ["JSON"] == "1":
    print(json.dumps({"verb": "heartbeat-gaps", "ok": True, "tier": "A",
                      "count": len(orphans), "monitors": orphans}, indent=2))
    sys.exit()
if not orphans:
    print("no orphaned push monitors — every push monitor has heartbeat history.")
    sys.exit()
for m in orphans:
    print(f"{m.get('id',''):>4}  {m.get('name','')}")
print(f"\n{len(orphans)} push monitor(s) at uptime1d=0 AND uptime30d=0 — never "
      "received a heartbeat.\nThe monitor exists; the pusher does not. Fix the "
      "pusher, do not delete the monitor.")
PY
}

# Read-only: sync.py --dry-run reports the diff without writing. Invoked as the
# direct expansion of `make uk-dry-run` rather than by shelling the make target —
# see the VALID_STACKS comment for why a make target cannot run over ssh here.
#
# The `git pull &&` that make target opens with is deliberately NOT reproduced.
# Tier A is the tier that gets allowlisted for unattended triage, and a pull
# fast-forwards the DEPLOYED homelab clone to whatever is on origin/master —
# including a half-finished commit pushed minutes earlier — which is a deploy
# action wearing a read verb's name. The preview is therefore against the
# checkout as deployed, which is the state you actually want previewed; if you
# need to know whether that checkout is behind origin, `sync-drift` answers it
# without writing anything, and `uk-sync` (Tier B, --confirm) owns the pull.
cmd_uk_dry_run() {
  AUDIT_TARGET="homelab"
  local out rc
  set +e
  out=$(ssh_run homelab "cd ~/homelab && op run --env-file=.env.tpl -- uptime-kuma/.venv/bin/python uptime-kuma/sync.py --dry-run --extra-config ../homelab-private/uptime-kuma/monitors.yaml" "$DEPLOY_TIMEOUT" 2>&1); rc=$?
  set -e
  if [ "$JSON" = 1 ]; then
    OUT="$out" RC="$rc" python3 -c '
import json, os
rc = int(os.environ["RC"])
print(json.dumps({"verb": "uk-dry-run", "ok": rc == 0, "tier": "A",
                  "exitCode": rc, "output": os.environ["OUT"],
                  "note": "previews the homelab checkout AS DEPLOYED; no git pull. "
                          "Run sync-drift to see whether that checkout is behind origin."},
                 indent=2))
'
    JSON_EMITTED=1
  else
    printf '%s\n' "$out"
  fi
  # The payload above already reports ok:false and the remote output, so in
  # --json mode remote_err only supplies the exit code (see JSON_EMITTED).
  [ "$rc" -eq 0 ] || remote_err "uk-dry-run failed (rc=$rc)"
}

# =============================================================================
# TIER B — mutating, idempotent, double-gated
# =============================================================================

# The bare `sync.py` invocation is what corrupts uptime-kuma: unset ${VAR}
# substitutes to "" and edit_monitor writes http://:8096/health and `Bearer `
# back into the DB. Running it while op run is broken re-corrupts everything it
# just repaired. Making env-check a hard, non-overridable pre-flight is the point
# of routing uk-sync through this script at all — the corrupting invocation is no
# longer reachable from here.
cmd_uk_sync() {
  require_why
  AUDIT_TARGET="homelab"

  [ "$JSON" = 1 ] || printf '==> pre-flight: env-check (op run must resolve every ref)\n'
  local pre_rc
  set +e
  ( JSON=0 cmd_env_check >/dev/null 2>&1 ); pre_rc=$?
  set -e
  [ "$pre_rc" -eq 0 ] || precond_err "env-check failed — refusing to sync. A sync with an unresolvable ref writes empty hostnames and empty bearer tokens into uptime-kuma. Run 'hermes-ops.sh env-check' and fix the dangling item first."

  PLAN=(
    "ssh -o BatchMode=yes -o ConnectTimeout=10 homelab \"cd ~/homelab && git pull && op run --env-file=.env.tpl -- uptime-kuma/.venv/bin/python uptime-kuma/sync.py --extra-config ../homelab-private/uptime-kuma/monitors.yaml\""
  )
  if [ "$CONFIRM" != 1 ] || [ "$DRY_RUN" = 1 ]; then
    run_plan
    return 0
  fi

  # Only on the confirmed path: the before/after pair is the verification, and a
  # dry run has nothing to verify. The counts are folded INTO the plan-results
  # object rather than printed after it — a `uk-sync --confirm --json` that
  # emitted the steps and then a second `uk-sync-verify` object handed the caller
  # two concatenated objects, which is a parse error, not a report.
  local before after verify
  before=$(argo_get "/uptime-kuma/status")
  PLAN_DEFER_JSON=1
  run_plan
  after=$(argo_get "/uptime-kuma/status")

  verify=$(python3 - "$before" "$after" <<'PY'
import json, sys
b, a = json.loads(sys.argv[1]), json.loads(sys.argv[2])
print(json.dumps({"beforeDown": b.get("down"), "afterDown": a.get("down"),
                  "beforeUp": b.get("up"), "afterUp": a.get("up")}))
PY
)

  if [ "$JSON" = 1 ]; then
    printf '%s\0' "${PLAN_RESULTS[@]}" | emit_plan_results 0 "$verify"
    JSON_EMITTED=1
    return 0
  fi

  python3 - "$verify" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
print(f"\nleaf down: {d['beforeDown']} -> {d['afterDown']}   "
      f"up: {d['beforeUp']} -> {d['afterUp']}")
print("Leaves flip first; group monitors cascade Up over the next ~10 min. "
      "Re-run `status` before calling it stable.")
PY
}

# Canonical fix for the Docker-IP-cascade and the stale MySQL pool: both are
# uptime-kuma holding dead client connections while every container is healthy.
# Recurs after Watchtower's 04:00 run recreates containers onto new bridge IPs.
cmd_restart_kuma() {
  require_why
  AUDIT_TARGET="homelab/uptime-kuma"
  PLAN=("ssh -o BatchMode=yes -o ConnectTimeout=10 homelab \"docker restart uptime-kuma\"")
  run_plan
}

cmd_restart() {
  local host="${1:-}" container="${2:-}"
  [ -n "$host" ] && [ -n "$container" ] \
    || usage_err "usage: hermes-ops.sh restart <homelab|vps> <container> --why \"<reason>\" [--confirm]"
  valid_host "$host"
  require_why
  valid_container "$host" "$container"
  AUDIT_TARGET="${host}/${container}"
  PLAN=("ssh -o BatchMode=yes -o ConnectTimeout=10 $host \"docker restart $container\"")
  run_plan
}

cmd_redeploy() {
  local host="${1:-}" stack="${2:-}"
  [ -n "$host" ] && [ -n "$stack" ] \
    || usage_err "usage: hermes-ops.sh redeploy <homelab|vps> <stack> --why \"<reason>\" [--confirm]"
  valid_host "$host"
  require_why

  local valid_stacks
  case "$host" in
    homelab) valid_stacks="$VALID_STACKS_homelab" ;;
    vps)     valid_stacks="$VALID_STACKS_vps" ;;
  esac
  # shellcheck disable=SC2086  # unquoted on purpose: the split IS the list lookup
  in_list "$stack" $valid_stacks \
    || usage_err "unknown stack for $host: $stack (must be one of: $valid_stacks)"
  AUDIT_TARGET="${host}/${stack}"

  case "$host" in
    homelab)
      PLAN=("ssh -o BatchMode=yes -o ConnectTimeout=10 homelab \"cd ~/homelab && git pull && op run --env-file=.env.tpl -- docker compose up -d --remove-orphans\"")
      ;;
    vps)
      # The VPS Makefile spells this `op run --account <acct> --env-file=...`.
      # The flag is a no-op under the server's service-account token — env-check
      # resolves the same template without it, on this exact host — so it is
      # dropped rather than baked into this repo.
      PLAN=("ssh -o BatchMode=yes -o ConnectTimeout=10 vps \"cd ~/vps && git pull && op run --env-file=.env.tpl -- docker compose -f compose.${stack}.yml up -d\"")
      ;;
  esac
  run_plan
}

cmd_cron_rerun() {
  local job="${1:-}"
  [ -n "$job" ] || usage_err "usage: hermes-ops.sh cron-rerun <${VALID_CRONS[*]}> --why \"<reason>\" [--confirm]"
  in_list "$job" "${VALID_CRONS[@]}" \
    || usage_err "unknown cron job: $job (must be one of: ${VALID_CRONS[*]})"
  require_why
  AUDIT_TARGET="homelab/cron/${job}"

  # Paths are ~-relative so no remote username is baked into this repo; the
  # crontab spells them absolutely, but ssh expands ~ to the same place.
  local script
  # shellcheck disable=SC2088  # the tilde is for the REMOTE shell, not this one:
  # these quotes are stripped before the value is interpolated into the ssh
  # command string, so the far side receives an unquoted ~ and expands it.
  case "$job" in
    vpn-watchdog)         script='~/homelab-private/scripts/vpn-watchdog.sh' ;;
    auto-update)          script='~/homelab-private/scripts/auto-update.sh' ;;
    garmin-auto-relogin)  script='~/homelab/scripts/garmin-auto-relogin.sh' ;;
    koinsight-stats-push) script='~/homelab-private/scripts/koinsight-stats-push.sh' ;;
  esac

  # Mirrors the crontab entry, including `. ~/.profile` — the crons source it for
  # OP_SERVICE_ACCOUNT_TOKEN, and a rerun that skips it reproduces a different
  # failure than the one being debugged. All four share ~/homelab/.env.tpl, which
  # is why env-check covers all four at once.
  # `cd ~/homelab` + a relative --env-file, because a tilde is NOT expanded after
  # `=` (verified: the remote shell echoes `--env-file=~/homelab/.env.tpl`
  # literally). The scripts cd to their own repo root via lib.sh, so the cwd this
  # sets is irrelevant to them.
  PLAN=("ssh -o BatchMode=yes -o ConnectTimeout=10 homelab \". ~/.profile; cd ~/homelab && op run --env-file=.env.tpl -- $script\"")
  run_plan
}

cmd_devhost_health() {
  require_why
  AUDIT_TARGET="mini"
  local script="$HOME/SourceRoot/dotfiles/scripts/devhost-health-check.sh"
  [ -f "$script" ] || precond_err "devhost-health-check.sh not found at $script"
  # Mutating only in that it pushes fresh heartbeats to UptimeKuma — which is the
  # point: it clears a MacMini push monitor without waiting a launchd interval.
  PLAN=("bash $script")
  run_plan
}

# Encodes the ONE correct sequence. `launchctl load` is deprecated and
# `kickstart -k` fails outright on a service that is not in the domain — and "not
# in the domain" is precisely the state this verb exists for (macOS smd boots
# agents out of gui/501 wholesale during session teardown; KeepAlive can never
# respawn something that has been removed). So: print the service first, and
# bootstrap ONLY when it is genuinely absent. A loaded service is left alone.
cmd_launchd_repair() {
  local label="${1:-}"
  [ -n "$label" ] || usage_err "usage: hermes-ops.sh launchd-repair <label> --why \"<reason>\" [--confirm]"
  in_list "$label" "${VALID_LAUNCHD[@]}" \
    || usage_err "unknown launchd label: $label (must be one of: ${VALID_LAUNCHD[*]})"
  require_why
  AUDIT_TARGET="mini/${label}"

  local uid plist state print_out print_rc
  uid=$(id -u)
  plist="$HOME/Library/LaunchAgents/${label}.plist"

  set +e
  print_out=$(launchctl print "gui/${uid}/${label}" 2>&1); print_rc=$?
  set -e

  if [ "$print_rc" -eq 0 ]; then
    state=$(printf '%s\n' "$print_out" | awk -F'= ' '/^[[:space:]]*state = /{print $2; exit}')
    if [ "$JSON" = 1 ]; then
      LABEL="$label" STATE="${state:-unknown}" python3 -c '
import json, os
print(json.dumps({"verb": "launchd-repair", "ok": True, "tier": "B",
                  "label": os.environ["LABEL"], "loaded": True,
                  "state": os.environ["STATE"], "action": "none",
                  "note": "service is registered in the domain; bootstrap would fail and "
                          "kickstart -k is not a repair for a loaded service. "
                          "If it is loaded but broken, that is a different incident."},
                 indent=2))
'
    else
      printf 'launchd: %s is loaded (state=%s). Nothing to repair.\n' "$label" "${state:-unknown}"
      printf 'bootstrap only applies to a service that was booted out of the domain.\n'
    fi
    return 0
  fi

  [ -f "$plist" ] || precond_err "$label is not loaded AND its plist is missing at $plist — this needs the dotfiles installer, not a bootstrap."
  need plutil
  plutil -lint "$plist" >/dev/null 2>&1 || precond_err "$plist fails plutil -lint — refusing to bootstrap a malformed plist."

  PLAN=("launchctl bootstrap gui/${uid} $plist")
  run_plan
}

# =============================================================================

show_help() {
  cat <<'EOF'
hermes-ops — bounded verb dispatcher for homelab/VPS/mini operations.

  hermes-ops.sh <verb> [args...] [--json] [--why "<reason>"] [--dry-run] [--confirm]

TIER A — read-only, safe to allowlist (no --why, no --confirm)
  status                        Leaf-only down count + docker counts (groups cascade and lie)
  monitors [filter]             All monitors, name-filtered, with uptime1d/30d
  containers <host>             Container state/health/restart counts
  logs <host> <container> [n]   Container logs, default n=200
  alerts [n]                    #alerts messages, newest first, default n=40
  env-check                     `op run --env-file=.env.tpl -- true` on homelab + vps.
                                One dangling 1Password ref breaks ALL four homelab
                                crons and corrupts the next uk-sync. Check it first.
  sync-drift                    HEAD vs live origin sha for homelab, homelab-private,
                                vps — on BOTH the mini clone and the server clone.
                                Only the server clone is deployed truth. Reads via
                                git ls-remote, so no ref is written; read `inSync`,
                                not the commit list, which needs cached objects.
                                Exits 3 if any clone could not be probed.
  kuma-db <preset> [args]       Fixed SQL presets, no free-form SQL:
                                  monitor-config    http/keyword url+hostname+port
                                  heartbeats <id>   last 25 beats for one monitor
                                  push-tokens       push monitors, token PREFIX only
                                  created-dates     newest 30 monitors by created_date
  heartbeat-gaps                Push monitors at uptime1d=0 AND uptime30d=0 —
                                orphans whose pusher was never built
  uk-dry-run                    Preview the uptime-kuma monitor sync against the
                                homelab checkout AS DEPLOYED (writes nothing, and
                                unlike `make uk-dry-run` does NOT git pull — that
                                would deploy. Use sync-drift for staleness.)

TIER B — mutating. Requires --why "<reason>"; prints a plan and changes NOTHING
         unless --confirm is also given.
  uk-sync                       env-check pre-flight (hard abort on failure), then
                                apply monitors, then report down-count before/after
  restart-kuma                  docker restart uptime-kuma — fixes the Docker-IP
                                cascade and the stale MySQL pool
  restart <host> <container>    Container name validated against the live list
  redeploy <host> <stack>       homelab: homelab · vps: networking, infra, monitoring
                                (homelab-private excluded: its `make up` is a full
                                VPN cycle, not a redeploy)
  cron-rerun <job>              vpn-watchdog | auto-update | garmin-auto-relogin |
                                koinsight-stats-push
  devhost-health                Run the mini health check (pushes fresh heartbeats)
  launchd-repair <label>        `launchctl print` first; bootstrap ONLY if the
                                service was booted out of the domain

HOSTS: homelab, vps

DELIBERATELY NOT IMPLEMENTED
  raw sqlite UPDATE on kuma.db  A running uptime-kuma overwrites direct DB writes
                                from its in-memory cache, and the fix is half a fix
                                anyway: it repairs empty-hostname URLs but not the
                                BetterStack keys, which only exist in 1Password.
                                uk-sync supersedes it.
  make down                     Stopping a stack is never mechanical recovery.
  restic-prune / restic-init    Need the B2 MASTER key (op://Private/*), which this
                                machine's secrets cache refuses by design.
  any 1Password write           Credential decisions are the user's, not the agent's.
  git push from a server        The homelab deploy key is read-only; it would fail.
  media mv/rm                   Not recoverable, not idempotent, not ops.
  free-form SQL / command / URL The escape hatch that would defeat the entire point.

--json      Exactly ONE JSON object on stdout per invocation, success or failure.
            A failure carries ok:false and exitCode in that same object; anything
            unstructured goes to stderr, so stdout always parses.

EXIT CODES  0 ok · 2 precondition failed · 3 remote failed · 64 usage error
AUDIT LOG   ~/Library/Logs/hermes-ops.log (one line per invocation, always)
EOF
}

# --- argument parsing --------------------------------------------------------
# Global flags are stripped anywhere in the line; what is left is the verb and
# its positional arguments. Every positional is validated by its verb.

ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --json)    JSON=1; shift ;;
    --confirm) CONFIRM=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --why)
      [ $# -ge 2 ] || usage_err "--why needs a reason"
      WHY="$2"; shift 2 ;;
    --why=*)   WHY="${1#--why=}"; shift ;;
    -h|--help) ARGS+=(help); shift ;;
    -*)        usage_err "unknown flag: $1" ;;
    *)         ARGS+=("$1"); shift ;;
  esac
done

VERB="${ARGS[0]:-}"
[ ${#ARGS[@]} -gt 0 ] && AUDIT_ARGS="${ARGS[*]:1}"

case "$VERB" in
  status)         cmd_status ;;
  monitors)       cmd_monitors "${ARGS[@]:1}" ;;
  containers)     cmd_containers "${ARGS[@]:1}" ;;
  logs)           cmd_logs "${ARGS[@]:1}" ;;
  alerts)         cmd_alerts "${ARGS[@]:1}" ;;
  env-check)      cmd_env_check ;;
  sync-drift)     cmd_sync_drift ;;
  kuma-db)        cmd_kuma_db "${ARGS[@]:1}" ;;
  heartbeat-gaps) cmd_heartbeat_gaps ;;
  uk-dry-run)     cmd_uk_dry_run ;;

  uk-sync)        cmd_uk_sync ;;
  restart-kuma)   cmd_restart_kuma ;;
  restart)        cmd_restart "${ARGS[@]:1}" ;;
  redeploy)       cmd_redeploy "${ARGS[@]:1}" ;;
  cron-rerun)     cmd_cron_rerun "${ARGS[@]:1}" ;;
  devhost-health) cmd_devhost_health ;;
  launchd-repair) cmd_launchd_repair "${ARGS[@]:1}" ;;

  help|"")        show_help ;;
  # No fallthrough to a shell, ever. An unknown verb is a usage error and the
  # valid set is printed so the caller can correct itself without guessing.
  *)              usage_err "unknown verb: $VERB
valid verbs:
  tier A  status monitors containers logs alerts env-check sync-drift kuma-db heartbeat-gaps uk-dry-run
  tier B  uk-sync restart-kuma restart redeploy cron-rerun devhost-health launchd-repair
  other   help" ;;
esac
