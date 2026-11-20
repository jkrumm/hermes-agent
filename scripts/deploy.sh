#!/usr/bin/env bash
# Ships the checked-out HEAD: `make setup` (symlinks, LaunchAgents), restart the gateway, then
# `make verify`. Restarts `hermes serve` (com.jkrumm.hermes-serve) alongside the gateway. On a failed verify, rolls the checkout back to HEAD~1 (detached) and repeats —
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
  # hermes serve (Desktop backend) imports config.yaml and patched modules at its own start too.
  launchctl kickstart -k "gui/$(id -u)/com.jkrumm.hermes-serve" || return 1
}

verify_with_retry() {
  # The API server needs a while after boot to report connected: seconds on an idle host,
  # minutes under load (2026-11-20, load 50: the secrets helper timed out and the API bound
  # minutes after the restart). Poll until VERIFY_TIMEOUT seconds (default 600) have passed,
  # not a fixed count, so a loaded host is waited out while a healthy one returns at once.
  # A restart first drains in-flight agent turns (gateway_state=draining) for as long as
  # they run — a drain is not a failure, so wait it out before the bounded polling. No cap:
  # a drain waits on agent turns (agent-limits rule); each poll is logged so a stuck one shows.
  local state deadline
  sleep 10
  state=$(jq -r '.gateway_state // ""' "$STATE" 2>/dev/null)
  while [ "$state" = draining ]; do
    echo "  … gateway draining in-flight turns, waiting"
    sleep 10
    state=$(jq -r '.gateway_state // ""' "$STATE" 2>/dev/null)
  done
  deadline=$((SECONDS + ${VERIFY_TIMEOUT:-600})) # starts after the drain: a long drain must not eat the poll budget
  while [ "$SECONDS" -lt "$deadline" ]; do
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
