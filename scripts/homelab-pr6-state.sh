#!/bin/bash
# Deterministic monitor value: state of homelab PR #6.
# Used as a cron `monitor` gate for the hardening follow-up job — unchanged
# output skips the agent tick, "MERGED" wakes it once.
gh pr view 6 --repo jkrumm/homelab --json state -q .state 2>/dev/null || echo UNKNOWN
