#!/bin/bash
# no-agent watchdog — the warden control plane runs from this checkout on master
# (`com.jkrumm.warden-loop` executes scripts/triage.py here), and warden's own
# merge path never pulls it (no deploy key for `warden`), so a merged fix is not
# live until this fast-forwards. Narrow by design: it waits for one specific
# merged commit (the §116 uk-proposer filter) and does nothing before that.
# Empty stdout is the trick — silent until there is news, then exactly one line.
set -u
REPO="$HOME/SourceRoot/warden"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.hermes/state}/warden-live-sync"
MARKER="OPAQUE_MONITOR_SOURCE"
mkdir -p "$STATE_DIR" 2>/dev/null || exit 0
REPORTED="$STATE_DIR/reported"
[ -e "$REPORTED" ] && exit 0

git -C "$REPO" fetch -q origin master 2>/dev/null || exit 0
# the marker exists only in the merged form of PR #6 — nothing to do before the merge
git -C "$REPO" show origin/master:scripts/triage.py 2>/dev/null | grep -q "$MARKER" || exit 0

if grep -q "$MARKER" "$REPO/scripts/triage.py" 2>/dev/null; then
  touch "$REPORTED"
  echo "warden live checkout already carries §116 (${MARKER}) — nothing to do."
  exit 0
fi

out=$(git -C "$REPO" merge --ff-only origin/master 2>&1)
if [ $? -eq 0 ]; then
  sha=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null)
  hits=$(grep -c "$MARKER" "$REPO/scripts/triage.py" 2>/dev/null || true)
  touch "$REPORTED"
  echo "warden live checkout fast-forwarded to ${sha} — §116 uk-proposer filter live in scripts/triage.py (${hits} marker lines); the 600s loop tick runs it from here."
else
  touch "$REPORTED"
  echo "warden live checkout could NOT fast-forward onto origin/master: $(printf '%s' "$out" | tail -2 | tr '\n' ' ')"
fi
exit 0
