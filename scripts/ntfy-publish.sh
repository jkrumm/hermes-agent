#!/usr/bin/env bash
# ntfy-publish — post one message to a self-hosted ntfy topic. Hermes has no ntfy
# platform, so cron jobs publish their own notices through this helper (installed
# with the scripts/ symlink at ~/.hermes/scripts/ntfy-publish.sh).
#
# Usage: ntfy-publish.sh <topic> [--title T] [--priority urgent|high|default|low]
#                        [--tags a,b] [body]      (body = last argument, else stdin)
#
# Unlike dotfiles' human-queue-notify-hook this one FAILS LOUD: any problem is one
# stderr line and a non-zero exit, so the cron job that called it shows as failed.
#
# The bearer comes from the secrets cache (`secrets-run read`, never `op`: a direct
# `op` call on the mini hangs on a biometric prompt). The server host is private and
# this repo is public: NTFY_URL, else the base-url line of the homelab repo's ntfy
# config, read at run time. Never write either into the repo.
#
# ntfy caps a message at 4096 bytes. Longer bodies are clipped at ~3800 bytes on a
# line boundary and end with a line saying the full text is in the job's cron output.
#
# Test overrides: SECRETS_RUN_BIN, CURL_BIN, NTFY_CONFIG, NTFY_URL.

set -u

NTFY_CONFIG="${NTFY_CONFIG:-$HOME/SourceRoot/homelab/config/ntfy/server.yml}"
SECRETS_RUN_BIN="${SECRETS_RUN_BIN:-$HOME/.local/bin/secrets-run}"
CURL_BIN="${CURL_BIN:-/usr/bin/curl}"
MAX_BYTES=3800

die() { echo "ntfy-publish: $1" >&2; exit 1; }

topic="" title="" priority="" tags="" body="" have_body=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --title)    [[ $# -ge 2 ]] || die "--title needs a value"; title="$2"; shift 2 ;;
    --priority) [[ $# -ge 2 ]] || die "--priority needs a value"; priority="$2"; shift 2 ;;
    --tags)     [[ $# -ge 2 ]] || die "--tags needs a value"; tags="$2"; shift 2 ;;
    --*)        die "unknown option $1" ;;
    *)
      if [[ -z "$topic" ]]; then topic="$1"; else body="$1"; have_body=1; fi
      shift ;;
  esac
done

[[ -n "$topic" ]] || die "usage: ntfy-publish.sh <topic> [--title T] [--priority P] [--tags a,b] [body]"
case "$priority" in ""|urgent|high|default|low) ;; *) die "bad priority '$priority'" ;; esac

if [[ "$have_body" == 0 ]]; then
  [[ -t 0 ]] && die "no body (pass it as the last argument or on stdin)"
  body=$(cat)
fi
[[ -n "$body" ]] || die "empty body"

[[ -x "$SECRETS_RUN_BIN" ]] || die "$SECRETS_RUN_BIN is not executable"
token=$("$SECRETS_RUN_BIN" read op://common/ntfy/TOKEN 2>/dev/null) || token=""
[[ -n "$token" ]] || die "ntfy token did not resolve (secrets-run read)"

base="${NTFY_URL:-}"
if [[ -z "$base" && -r "$NTFY_CONFIG" ]]; then
  base=$(sed -n 's/^base-url:[[:space:]]*"\{0,1\}\([^"[:space:]]*\)"\{0,1\}[[:space:]]*$/\1/p' "$NTFY_CONFIG" | head -1)
fi
[[ -n "$base" ]] || die "ntfy base URL not found (set NTFY_URL or provide NTFY_CONFIG)"

message=$(printf '%s\n' "$body" | LC_ALL=C awk -v max="$MAX_BYTES" '
  { l = length($0) + 1
    if (n + l > max) { clipped = 1; if (n == 0) print substr($0, 1, max); exit }
    print; n += l }
  END { if (clipped) print "\n(clipped - the full text is in the job'"'"'s cron output)" }')

args=(-fsS --max-time 10 -o /dev/null -X POST "${base%/}/$topic"
  -H "Authorization: Bearer $token" -H "Markdown: yes")
[[ -n "$title" ]] && args+=(-H "Title: $title")
[[ -n "$priority" ]] && args+=(-H "Priority: $priority")
[[ -n "$tags" ]] && args+=(-H "Tags: $tags")

err=$("$CURL_BIN" "${args[@]}" --data-binary "$message" 2>&1 >/dev/null) \
  || die "publish to topic '$topic' failed: $(printf '%s' "$err" | tr '\n' ' ' | cut -c1-200)"
exit 0
