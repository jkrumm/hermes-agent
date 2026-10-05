#!/usr/bin/env bash
# Ships the checked-out HEAD: `make setup` (symlinks, LaunchAgents), restart the gateway, then
# `make verify`. On a failed verify, rolls the checkout back to HEAD~1 (detached) and repeats —
# only when the working tree is clean; otherwise it refuses and says how to recover by hand.
# The checkout IS the live config (symlinked into ~/.hermes), so "deploy" = apply + restart.
# Restarting kills in-flight gateway sessions — run it when no turn is mid-flight.
set -uo pipefail
cd "$(dirname "$0")/.."

STATE="$HOME/.hermes/gateway_state.json"

prev=$(git rev-parse --verify --quiet HEAD~1) || prev=""
head=$(git rev-parse --short HEAD)

apply_and_restart() {
  make --no-print-directory setup >/dev/null || return 1
  launchctl kickstart -k "gui/$(id -u)/ai.hermes.gateway" || return 1
}

verify_with_retry() {
  # Slack + the API server need a while after boot to report connected.
  # A restart first drains in-flight agent turns (gateway_state=draining) for as long as
  # they run — a drain is not a failure, so wait it out before the bounded retries. No cap:
  # a drain waits on agent turns (agent-limits rule); each poll is logged so a stuck one shows.
  local n state
  sleep 10
  state=$(jq -r '.gateway_state // ""' "$STATE" 2>/dev/null)
  while [ "$state" = draining ]; do
    echo "  … gateway draining in-flight turns, waiting"
    sleep 10
    state=$(jq -r '.gateway_state // ""' "$STATE" 2>/dev/null)
  done
  for n in 1 2 3 4 5 6; do
    make --no-print-directory verify >/dev/null 2>&1 && return 0
    sleep 8
  done
  make --no-print-directory verify
  return 1
}

echo "deploying $head"
if apply_and_restart && verify_with_retry; then
  echo "deployed $head and verified"
  exit 0
fi

echo "deploy of $head FAILED (setup, restart or verify)"
if [ -z "$prev" ]; then
  echo "no previous commit to roll back to"
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "refusing to roll back: working tree is not clean. Commit/stash, then 'git switch --detach $prev && make deploy'."
  exit 1
fi

echo "rolling back to $(git rev-parse --short "$prev")"
git switch --detach "$prev" || exit 1
if apply_and_restart && verify_with_retry; then
  echo "################################################################"
  echo "ROLLED BACK: the checkout is now DETACHED at $(git rev-parse --short "$prev") (deploy of $head failed)."
  echo "Fix forward, then return with: git switch master"
  echo "################################################################"
else
  echo "################################################################"
  echo "ROLLBACK ALSO FAILED. Checkout is DETACHED at $(git rev-parse --short "$prev"). Inspect: make logs"
  echo "Return with: git switch master"
  echo "################################################################"
fi
exit 1
