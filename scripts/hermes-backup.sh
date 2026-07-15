#!/bin/zsh
# Daily Hermes backup — rsync ~/.hermes/ to homelab HDD, then ping UptimeKuma.
# Excludes large/regenerable artifacts. State.db (conversation history) IS
# included. Cron: 0 3 * * *

set -u

SECRETS_RUN="$HOME/.local/bin/secrets-run"
SRC="$HOME/.hermes/"
DEST="homelab:/mnt/hdd/backups/hermes/"
# cron runs with a minimal PATH; prepend Homebrew so secrets-run finds sops+jq (its
# cache backend) and `timeout` resolves. Prepend (not replace) to preserve cron's PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Resolve the UptimeKuma push URL from op://hermes/uptime-kuma/backup-push-url via
# `secrets-run read` (encrypted cache on the mini, biometric op on the MacBook), bounded
# by `timeout`. A resolution failure is non-fatal: the backup still runs and exits with
# rsync's code; only the success ping is skipped, so UptimeKuma alerts on the missing
# heartbeat. A failed ping never overrides rsync's exit code (RC is captured before it).
PUSH_URL=""
[[ -x "$SECRETS_RUN" ]] && PUSH_URL=$(timeout 10 "$SECRETS_RUN" read op://hermes/uptime-kuma/backup-push-url 2>/dev/null)

/usr/bin/rsync -az --delete \
  --exclude='audio_cache/' \
  --exclude='image_cache/' \
  --exclude='cache/' \
  --exclude='sandboxes/' \
  --exclude='sessions/' \
  --exclude='*.lock' \
  --exclude='*.pid' \
  --exclude='hermes-agent/' \
  --exclude='.update_check' \
  --exclude='.skills_prompt_snapshot.json' \
  "$SRC" "$DEST"

RC=$?

if [[ $RC -eq 0 && -n "${PUSH_URL:-}" ]]; then
  /usr/bin/curl -fsS --max-time 10 "$PUSH_URL" >/dev/null
fi

exit $RC
