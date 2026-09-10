#!/usr/bin/env bash
# The dispatch bridge is now warden/scripts/warden (a Python CLI; hermes-cc.sh
# itself was retired 2026-09-10). This file stays only because its exact path
# is load-bearing: the Hermes-side guards (test_raw_agent_guard.py,
# test_repo_write_guard.py, patches/tirith-hermes-guards.patch) key on it.
exec "${WARDEN_CLI:-$HOME/SourceRoot/warden/scripts/warden}" "$@"
