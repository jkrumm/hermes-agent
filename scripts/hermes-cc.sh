#!/usr/bin/env bash
# hermes-cc.sh moved wholesale to warden/scripts/hermes-cc.sh on 2026-09-10 — the
# control plane it writes into (~/.warden/warden.db) already lives there, and the
# Hermes-side guards (test_raw_agent_guard.py, test_repo_write_guard.py,
# patches/tirith-hermes-guards.patch) key on this exact path, so this shim stays.
exec "${HERMES_CC_BIN:-$HOME/SourceRoot/warden/scripts/hermes-cc.sh}" "$@"
