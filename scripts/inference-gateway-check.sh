#!/bin/bash
# Inference-gateway check — the agw gateway on 127.0.0.1:7794 that every Hermes model call goes
# through (NOT Hermes' own messaging gateway). Standalone so the three callers — hermes-liveness.sh
# (zsh, launchd), verify.sh (bash) and `make status` — share one implementation by running it as a
# subprocess (`/bin/bash scripts/inference-gateway-check.sh`), no sourcing across shells.
#
# Two checks, in order, one output line each, prefixed `ok ` or `fail ` (callers map the prefix):
#   health  GET /health answers within 5 s with status "ok"            (`ok inference gateway answering (build <id>)`)
#   token   GET /anthropic/v1/models with the `hermes=` door token     (a catalog read: no usage row, no pick,
#           within 10 s; passes on 2xx, 429 and 5xx (the gateway        costs nothing)
#           authenticated, then the provider answered); fails on 401/403,
#           no answer, or any other status
# If health fails the token line is `fail door token skipped: inference gateway unreachable`.
# Exit 0 only when both pass. Arguments: none (both), `health` or `token` (one check, for debugging).
#
# The token is read from the 0600 file inside this script and handed to curl as a config on stdin
# (`-K -`): never in argv, never echoed, never logged. Test override: HERMES_DOOR_TOKENS_FILE points at
# another tokens file.
set -uo pipefail

BASE="http://127.0.0.1:7794"
TOKENS="${HERMES_DOOR_TOKENS_FILE:-$HOME/.agent-workflows/data/door-tokens}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

health() {
  local out code body status build
  # -s without -S keeps curl's own error text out of the body jq parses; the status code rides on the last line.
  out=$(curl -s --max-time 5 -w '\n%{http_code}' "$BASE/health" 2>/dev/null) || out=""
  code="${out##*$'\n'}"
  body="${out%$'\n'*}"
  if [[ -z "$out" || "$code" == "000" ]]; then
    echo "inference gateway ($BASE) not answering within 5 s"; return 1
  fi
  [[ "$code" == 2?? ]] || { echo "inference gateway /health -> HTTP $code"; return 1; }
  status=$(jq -r '.status // ""' <<<"$body" 2>/dev/null)
  [[ "$status" == "ok" ]] || { echo "inference gateway /health status=${status:-unparseable}"; return 1; }
  build=$(jq -r '.build // "unknown"' <<<"$body")
  echo "inference gateway answering (build $build)"
}

token() {
  local line tok code
  [[ -r "$TOKENS" ]] || { echo "door token file missing or unreadable ($TOKENS)"; return 1; }
  line=$(grep -E '^hermes=' "$TOKENS" | head -1 || true)
  [[ -n "$line" ]] || { echo "no hermes= line in $TOKENS"; return 1; }
  tok=$(printf '%s' "${line#hermes=}" | tr -d '[:space:]')
  # Also keeps a stray quote or newline out of the curl config below.
  [[ "$tok" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "malformed hermes= line in $TOKENS"; return 1; }
  # printf is a builtin (no argv); the config reaches curl on stdin.
  code=$(printf 'header = "authorization: Bearer %s"\n' "$tok" \
    | curl -sS -o /dev/null -w '%{http_code}' --max-time 10 -K - "$BASE/anthropic/v1/models" 2>/dev/null) || code=""
  # The gateway authenticates before it forwards: a 429/5xx means the token was good and the
  # provider is the problem. Any other 4xx (404, 400, ...) is the gateway rejecting the probe itself.
  case "$code" in
    2??) echo "door token accepted (HTTP $code)" ;;
    429|5??) echo "door token accepted (upstream HTTP $code)" ;;
    401|403) echo "door token refused (HTTP $code)"; return 1 ;;
    ""|000) echo "door token probe got no response within 10 s"; return 1 ;;
    *) echo "door token probe -> HTTP $code"; return 1 ;;
  esac
}

report() { # report <check>: prefix its single line with ok/fail, return its status
  local msg
  if msg=$("$1"); then echo "ok $msg"; else echo "fail $msg"; return 1; fi
}

case "${1:-all}" in
  health) report health ;;
  token) report token ;;
  all)
    if report health; then
      report token
    else
      echo "fail door token skipped: inference gateway unreachable"; exit 1
    fi
    ;;
  *) echo "usage: $0 [health|token]" >&2; exit 2 ;;
esac
