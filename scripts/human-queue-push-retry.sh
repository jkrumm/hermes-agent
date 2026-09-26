#!/bin/bash
# no_agent cron worker (every 15 min): unstick a parked human-queue request by
# re-pushing the MacBook approval dialog once the MacBook is reachable again,
# then report its resolution exactly once.
#
# `ask-human.sh ask` pushes the approval dialog at enqueue time. An unreachable
# MacBook (asleep) drops the request into the queue instead, where the median
# resolution is days — which is what this closes. It prints nothing while the
# MacBook is away, pushes at most one dialog per RETRY_AFTER, and emits a single
# report line when the request resolves (empty stdout delivers nothing — the
# no_agent watchdog pattern). After that it is inert.
#
# The cmd stays the mini's *proposal*: `push` shows the exact string in a native
# dialog on the MacBook and only a clicked "Run" executes it, unmodified.
#
# Usage: human-queue-push-retry.sh [<request-id>]   (id defaults to the one
#        currently parked, see DEFAULT_ID)
set -u

DEFAULT_ID="${HUMAN_QUEUE_RETRY_ID:-20260926T132306-28724}"
ID="${1:-$DEFAULT_ID}"
HOMELAB_HOST=homelab      # the pushed grant opens a port here
HOMELAB_PORT=1143

Q="${XDG_STATE_HOME:-$HOME/.local/state}/human-queue"
RES="$Q/$ID.res"
REPORTED="$Q/.push-retry-$ID.reported"
ATTEMPT="$Q/.push-retry-$ID.attempt"
ASK="$HOME/SourceRoot/dotfiles/scripts/ask-human.sh"
TS=/opt/homebrew/bin/tailscale
RETRY_AFTER=21600         # seconds between dialogs (6h)
SSH=(ssh -q -o BatchMode=yes -o ConnectTimeout=8)

# status<TAB>exit<TAB>output_tail  — tolerant of a malformed/partial .res
res_fields() {
  python3 - "$1" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("unreadable\t-\t")
    raise SystemExit
tail = " ".join((d.get("output_tail") or "").split())[:200]
print("%s\t%s\t%s" % (d.get("status", "?"), d.get("exit", "-"), tail))
PY
}

homelab_ip() {
  "$TS" status --json 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    raise SystemExit
for p in d.get("Peer", {}).values():
    if p.get("HostName") == sys.argv[1]:
        print(p["TailscaleIPs"][0]); break
' "$HOMELAB_HOST" 2>/dev/null
}

# 1. Resolved — report once, then stay silent for good.
if [ -f "$RES" ]; then
  [ -f "$REPORTED" ] && exit 0
  touch "$REPORTED"
  IFS="$(printf '\t')" read -r status code tail < <(res_fields "$RES")
  line="Human-Queue $ID abgeschlossen: status=$status exit=$code"
  [ -n "${tail:-}" ] && line="$line — $tail"
  if [ "$status" = "done" ]; then
    ip="$(homelab_ip)"
    probe="nicht geprüft"
    if [ -n "$ip" ]; then
      if "${SSH[@]}" vps "timeout 5 bash -c \"cat < /dev/null > /dev/tcp/$ip/$HOMELAB_PORT\"" >/dev/null 2>&1; then
        probe="offen"
      else
        probe="weiter blockiert"
      fi
    fi
    line="$line · VPS → $HOMELAB_HOST:$HOMELAB_PORT $probe"
  fi
  printf '%s\n' "$line"
  exit 0
fi

# 2. Still open — at most one dialog per RETRY_AFTER, silent in between.
if [ -f "$ATTEMPT" ]; then
  mtime="$(stat -f %m "$ATTEMPT" 2>/dev/null || echo 0)"
  [ "$(( $(date +%s) - mtime ))" -lt "$RETRY_AFTER" ] && exit 0
fi

# 3. Only knock at a MacBook that answers; otherwise say nothing at all.
"${SSH[@]}" iumac true 2>/dev/null || exit 0
touch "$ATTEMPT"
# Detached on purpose: the dialog gives up after 600s (HUMAN_QUEUE_DIALOG_SECONDS
# on the MacBook side), and a cron tick must not sit there waiting for a click.
# The MacBook writes the resolution back to this queue itself, so the next tick
# reports it whether or not this ssh is still alive.
nohup timeout 900 bash "$ASK" push "$ID" >/dev/null 2>&1 &
exit 0
