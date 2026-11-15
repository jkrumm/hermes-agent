#!/usr/bin/env bash
# Is the installed Hermes behind the newest stable upstream release? (`make upstream-check`)
# Exit 0 = current (or ahead), 1 = behind, 2 = could not tell (fetch or version failed).
# Read-only apart from `git fetch --tags` into the upstream checkout. Never updates or restarts
# anything: the factory lead that picks up exit 1 runs the /hermes-update skill and `make deploy`.
#
# Stable tag = `vMAJOR.MINOR.PATCH` with a 1-3 digit major. That excludes the daily
# `vX.Y.Z+canary.*` tags, `rc.N-*` / `abandoned-rc.N-*` tags and the pre-0.21 date tags (`v2026.9.24`).
# Overrides (tests): HERMES_SRC = upstream checkout, HERMES_BIN = the hermes CLI.
set -uo pipefail

SRC="${HERMES_SRC:-$HOME/.hermes/hermes-agent}"
BIN="${HERMES_BIN:-hermes}"
STABLE='^v[0-9]{1,3}\.[0-9]+\.[0-9]+$'

fail() { echo "  ✗ upstream-check: $1" >&2; exit 2; }

[[ -d "$SRC/.git" || -f "$SRC/.git" ]] || fail "no upstream checkout at $SRC"

installed=$("$BIN" --version 2>/dev/null | grep -Eo -m1 'v[0-9]{1,3}\.[0-9]+\.[0-9]+' | head -n1 || true)
[[ -n "$installed" ]] || fail "could not read the installed version from '$BIN --version'"

timeout 120 git -C "$SRC" fetch --quiet --tags origin 2>/dev/null || fail "git fetch --tags origin failed in $SRC"

latest=$(git -C "$SRC" tag --list | grep -E "$STABLE" | sort -V | tail -n 1 || true)
[[ -n "$latest" ]] || fail "no stable tag found in $SRC"

behind=$(git -C "$SRC" rev-list --count "HEAD..$latest" 2>/dev/null || echo "?")

echo "installed: $installed"
echo "latest:    $latest"
echo "behind:    $behind commits"

if [[ "$installed" == "$latest" ]] || [[ "$(printf '%s\n%s\n' "$installed" "$latest" | sort -V | tail -n 1)" == "$installed" ]]; then
  echo "  ✓ current"
  exit 0
fi

echo "  ✗ behind $latest — run the /hermes-update skill, then make deploy"
exit 1
