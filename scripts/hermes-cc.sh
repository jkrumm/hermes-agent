#!/usr/bin/env bash
# The dispatch bridge is now warden/scripts/warden (a Python CLI; hermes-cc.sh
# itself was retired 2026-09-10). This file stays only because its exact path
# is the one every other doc and script here references.
exec "${WARDEN_CLI:-$HOME/SourceRoot/warden/scripts/warden}" "$@"
