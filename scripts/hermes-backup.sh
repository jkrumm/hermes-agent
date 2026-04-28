#!/bin/zsh
# Daily Hermes backup — rsync ~/.hermes/ to homelab HDD, then ping UptimeKuma.
# Excludes large/regenerable artifacts. State.db (conversation history) IS
# included. Cron: 0 3 * * *

set -u

ENV_FILE="$HOME/.hermes/.env"
SRC="$HOME/.hermes/"
DEST="homelab:/mnt/hdd/backups/hermes/"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[hermes-backup] $ENV_FILE missing — aborting" >&2
  exit 1
fi

PUSH_URL=$(grep -E '^UPTIME_PUSH_BACKUP=' "$ENV_FILE" | cut -d= -f2-)

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
