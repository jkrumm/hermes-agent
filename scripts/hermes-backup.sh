#!/bin/zsh
# Daily Hermes backup — rsync ~/.hermes/ to homelab HDD, then ping UptimeKuma.
# Excludes large/regenerable artifacts. State.db (conversation history) IS
# included. Runs at 03:00 via the com.jkrumm.hermes-backup LaunchAgent
# (launchd/, installed by `make setup`).

set -u

SECRETS_RUN="$HOME/.local/bin/secrets-run"
SRC="$HOME/.hermes/"
DEST="homelab:/mnt/hdd/backups/hermes/"
# launchd hands the job a minimal PATH (as cron did); prepend Homebrew so secrets-run
# finds sops+jq (its cache backend) and `timeout` resolves. Prepend, not replace.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Resolve the UptimeKuma push URL from op://hermes/uptime-kuma/backup-push-url via
# `secrets-run read` (encrypted cache on the mini, biometric op on the MacBook), bounded
# by `timeout`. A resolution failure is non-fatal: the backup still runs and exits with
# rsync's code; only the success ping is skipped, so UptimeKuma alerts on the missing
# heartbeat. A failed ping never overrides rsync's exit code (RC is captured before it).
# Single-instance lock. Two concurrent `rsync --delete` runs onto the same
# destination race each other's file list — one deleting what the other is still
# writing. Nothing scheduled this twice by design, but the crontab→LaunchAgent
# migration (2026-08-02) leaves both schedulers armed until `make cron-migrate`
# clears the old entries, and that cleanup needs Full Disk Access this machine
# cannot grant unattended. The lock makes the overlap harmless rather than
# depending on the cleanup happening first.
#
# `mkdir` is the atomic primitive — it fails if the dir exists and cannot
# half-exist the way a bare PID file can. Same shape as dotfiles/brain/brain-sync.sh.
LOCK_DIR="${HERMES_BACKUP_LOCK_DIR:-$HOME/Library/Caches/hermes-backup.lock}"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  HOLDER=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
  # `kill -0` returns EPERM (not ESRCH) for a live pid owned by another user and
  # cannot tell the two apart; absence from `ps` is unambiguous.
  if [[ -n "$HOLDER" ]] && ps -p "$HOLDER" >/dev/null 2>&1; then
    echo "another backup (pid $HOLDER) is still running — skipping this run" >&2
    exit 0
  fi
  LOCK_BORN=$(stat -f %m "$LOCK_DIR" 2>/dev/null || echo 0)
  LOCK_AGE=$(( $(date +%s) - LOCK_BORN ))
  # A pidless lock is either a run that died between mkdir and the write, or one
  # claiming it right now. Age decides — treating a fresh one as abandoned is how
  # two runs end up sharing a lock.
  if [[ -z "$HOLDER" && $LOCK_AGE -lt 60 ]]; then
    echo "$LOCK_DIR has no pid yet and is only ${LOCK_AGE}s old — skipping this run" >&2
    exit 0
  fi
  echo "reclaiming the lock left by pid ${HOLDER:-unknown} (${LOCK_AGE}s old)" >&2
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" 2>/dev/null || { echo "lost the race for $LOCK_DIR — skipping this run" >&2; exit 0; }
fi
printf '%s' "$$" >"$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT INT TERM

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
