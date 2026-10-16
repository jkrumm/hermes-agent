#!/bin/zsh
# Daily Hermes backup — rsync ~/.hermes/ to homelab HDD, the exit code is the verdict.
# Excludes large/regenerable artifacts and a plaintext ~/.hermes/.env (there is
# none by design — `hermes model` recreates one, and a copy of it must never
# reach homelab). State.db (conversation history) IS included. Runs at 03:00 via the com.jkrumm.hermes-backup LaunchAgent
# (launchd/, installed by `make setup`).
#
# SQLite's transient sidecars (*-shm, *-wal) are excluded. They are meaningless
# without the main .db, which IS transferred, and they race their owner: the
# gateway checkpoints kanban.db/state.db while rsync walks them, the sidecar
# disappears between the file list and the transfer, rsync reports "open: No such
# file or directory" and exits 23 (partial transfer) — which suppresses the
# Kuma push even though every real file shipped, so a healthy backup reads
# as a dead one.

set -u

SRC="$HOME/.hermes/"
DEST="homelab:/mnt/hdd/backups/hermes/"
# launchd hands the job a minimal PATH; prepend Homebrew. Prepend, not replace.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# The plist runs this under `jobrun` (dotfiles): each run is recorded and graded, and
# `--kuma op://hermes/uptime-kuma/backup-push-url` pings the 25 h backstop on rc 0, so
# this script no longer resolves or pushes anything itself.
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

# --delete-excluded: the excludes are things that must NOT exist on homelab (a stray
# plaintext /.env, sidecars), so --delete has to remove them too. Without it a directory
# holding only excluded files (sidecars-excluded-20260921) could never be deleted, and
# rsync reported "cannot delete non-empty directory" every night while still exiting 0.
RSYNC_OUT=$(mktemp "${TMPDIR:-/tmp}/hermes-backup.XXXXXX")
/usr/bin/rsync -az --delete --delete-excluded \
  --exclude='audio_cache/' \
  --exclude='image_cache/' \
  --exclude='cache/' \
  --exclude='sandboxes/' \
  --exclude='sessions/' \
  --exclude='*.lock' \
  --exclude='*.pid' \
  --exclude='*-shm' \
  --exclude='*-wal' \
  --exclude='/.env' \
  --exclude='hermes-agent/' \
  --exclude='.update_check' \
  --exclude='.skills_prompt_snapshot.json' \
  "$SRC" "$DEST" >"$RSYNC_OUT" 2>&1
RC=$?
cat "$RSYNC_OUT"

# rsync exits 0 when it merely failed to delete ("cannot delete ..."), so a broken
# rotation passed for a good backup. Treat any such line as a failure.
if [[ $RC -eq 0 ]] && grep -q 'cannot delete' "$RSYNC_OUT"; then
  echo "rsync could not delete everything it should — failing the run" >&2
  RC=1
fi
rm -f "$RSYNC_OUT"

exit $RC
