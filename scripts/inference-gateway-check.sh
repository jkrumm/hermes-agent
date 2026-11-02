#!/bin/bash
# Inference-gateway check — the agw gateway on 127.0.0.1:7794 that every Hermes model call goes
# through (NOT Hermes' own messaging gateway). Standalone so the three callers — hermes-liveness.sh
# (zsh, launchd), verify.sh (bash) and `make status` — share one implementation by running it as a
# subprocess (`/bin/bash scripts/inference-gateway-check.sh [health|token|all]`), no sourcing across shells.
#
#   health  GET /health answers within 5 s with status "ok"           (prints "build <id>")
#   token   GET /anthropic/v1/models with the `hermes=` door token    (a catalog read: no usage row,
#           fails only on 401/403 or no answer within 10 s             no pick, costs nothing)
#   all     both, health first (default)
#
# Prints ONE line (the reason on failure, a detail on success) and exits 0 / 1. The token is read from
# the 0600 file inside this script and handed to curl as a config on stdin (`-K -`): never in argv,
# never echoed, never logged. Test override: HERMES_DOOR_TOKENS_FILE points at another tokens file.
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
  echo "build $build"
}

token() {
  local line tok code
  [[ -r "$TOKENS" ]] || { echo "door token file missing or unreadable ($TOKENS)"; return 1; }
  line=$(grep -E '^hermes=' "$TOKENS" | head -1 || true)
  tok="${line#hermes=}"
  [[ -n "$line" && -n "$tok" ]] || { echo "no hermes= line in $TOKENS"; return 1; }
  # printf is a builtin (no argv); the config reaches curl on stdin.
  code=$(printf 'header = "authorization: Bearer %s"\n' "$tok" \
    | curl -sS -o /dev/null -w '%{http_code}' --max-time 10 -K - "$BASE/anthropic/v1/models" 2>/dev/null) || code=""
  # The gateway authenticates before it forwards, so any answer but 401/403 proves the token: an
  # upstream 429/5xx is the provider's problem, not a refused credential.
  case "$code" in
    2??) echo "door token accepted (HTTP $code)" ;;
    401|403) echo "door token refused (HTTP $code)"; return 1 ;;
    ""|000) echo "inference gateway token probe got no response within 10 s"; return 1 ;;
    *) echo "door token accepted (upstream HTTP $code)" ;;
  esac
}

case "${1:-all}" in
  health) health ;;
  token) token ;;
  all)
    out=$(health) || { echo "$out"; exit 1; }
    tout=$(token) || { echo "$tout"; exit 1; }
    echo "$out; $tout"
    ;;
  *) echo "usage: $0 [health|token|all]" >&2; exit 2 ;;
esac
