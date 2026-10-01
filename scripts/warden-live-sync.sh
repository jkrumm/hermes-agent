#!/bin/bash
# no-agent watchdog — the warden control plane runs from this checkout on master
# (`com.jkrumm.warden-loop` executes scripts/triage.py here), and warden's own
# merge path never pulls it (no deploy key for `warden`), so a merged fix is not
# live until this syncs. Narrow by design: it waits for one specific merged
# commit (the §116 uk-proposer filter, marker OPAQUE_MONITOR_SOURCE in
# scripts/triage.py) and does nothing before that.
#
# The checkout is deliberately ahead of origin/master between PRs: the loop
# commits its own auto-proposed policy additions locally and NEVER pushes
# (`scripts/triage.py` says so by name). So a fast-forward is the common case,
# not the guaranteed one — hence the plain-merge fallback, which is what the
# repo's own history does by hand ("merge: origin/master … into the local tree").
# A conflicted merge is aborted, so a refusal leaves the checkout exactly as it
# was found.
#
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

how=""
merged=0
if out=$(git -C "$REPO" merge --ff-only origin/master 2>&1); then
  how="fast-forward"; merged=1
elif out=$(git -C "$REPO" merge --no-edit origin/master 2>&1); then
  how="merge of origin/master into the local tree"; merged=1
elif [ -n "$(git -C "$REPO" ls-files -u 2>/dev/null | head -1)" ]; then
  git -C "$REPO" merge --abort >/dev/null 2>&1
  out="conflicted merge of origin/master, aborted: $(printf '%s' "$out" | tail -2 | tr '\n' ' ')"
fi

# both the remote tip being in our history and the marker in the working file are
# required — a conflicted merge leaves the marker text in the file, and a merge
# that did not actually land must never be reported as live
if [ "$merged" = 1 ] && git -C "$REPO" merge-base --is-ancestor origin/master HEAD 2>/dev/null \
   && grep -q "$MARKER" "$REPO/scripts/triage.py" 2>/dev/null; then
  sha=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null)
  hits=$(grep -c "$MARKER" "$REPO/scripts/triage.py" 2>/dev/null || true)
  touch "$REPORTED"
  echo "warden live checkout synced to ${sha} (${how}) — §116 uk-proposer filter now in scripts/triage.py (${hits} marker lines); the 600s loop tick runs it from here."
else
  touch "$REPORTED"
  echo "warden live checkout could NOT take §116 from origin/master: $(printf '%s' "$out" | tail -2 | tr '\n' ' ')"
fi
exit 0
