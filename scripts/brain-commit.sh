#!/bin/zsh
# brain-commit — commit (and push) the Obsidian vault under brain-sync's lock.
#
# The obsidian and wildrift skills instruct Hermes to commit after writing,
# because on this mini the brain-sync LaunchAgent pulls and pushes every 5 min
# but never commits. A bare `git -C ~/SourceRoot/brain commit` composed by the
# agent races that job for .git/index.lock. This script takes the SAME mkdir
# lock brain-sync.sh, brain-backup.sh, audio-gateway's brain-note.ts and
# project-narratives.py take, then adds, commits, and pushes (fail-soft — a
# rejected push is logged, brain-sync pushes on its next tick).
#
# Usage: brain-commit.sh "<commit message>" [path ...]
#   No paths → `git add -A`. Exit 0 on commit; 0 with "nothing to commit"; 3
#   when the lock is busy (nothing committed — say so, retry later); 1 on a
#   git failure. Every git call names the vault (`git -C`), per the
#   raw_repo_write guard's vault exemption.
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

VAULT="$HOME/SourceRoot/brain"
LOCK_DIR="${BRAIN_SYNC_LOCK_DIR:-$HOME/Library/Caches/brain-sync.lock}"
MSG="${1:-}"
[[ -n "$MSG" ]] || { print -u2 "brain-commit: usage: brain-commit.sh \"<message>\" [path ...]"; exit 64; }
shift
[[ -d "$VAULT/.git" ]] || { print -u2 "brain-commit: $VAULT is not a git checkout"; exit 2; }

# Same lock semantics as brain-sync.sh: mkdir is atomic; a live holder wins; a
# pidless lock younger than 60s is another run claiming it; anything else is a
# corpse and is reclaimed. Retry a held lock a few times before giving up —
# the sync tick is short.
attempt=0
while ! mkdir "$LOCK_DIR" 2>/dev/null; do
  holder=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
  if [[ -n "$holder" ]] && ps -p "$holder" >/dev/null 2>&1; then
    attempt=$((attempt + 1))
    if (( attempt > 6 )); then
      print -u2 "brain-commit: brain-sync (pid $holder) holds the vault lock — nothing committed, retry in a minute"
      exit 3
    fi
    sleep 5; continue
  fi
  born=$(stat -f %m "$LOCK_DIR" 2>/dev/null || echo 0)
  age=$(( $(date +%s) - born ))
  if [[ -z "$holder" && $age -lt 60 ]]; then
    attempt=$((attempt + 1))
    (( attempt > 6 )) && { print -u2 "brain-commit: vault lock is being claimed — nothing committed, retry in a minute"; exit 3; }
    sleep 5; continue
  fi
  print -u2 "brain-commit: reclaiming the lock left by pid ${holder:-unknown} (${age}s old)"
  rm -rf "$LOCK_DIR"
done
printf '%s' "$$" >"$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT INT TERM

if (( $# > 0 )); then
  git -C "$VAULT" add -- "$@" || exit 1
else
  git -C "$VAULT" add -A || exit 1
fi
if git -C "$VAULT" diff --cached --quiet; then
  echo "brain-commit: nothing to commit"
  exit 0
fi
git -C "$VAULT" commit -q -m "$MSG" || exit 1
echo "brain-commit: committed $(git -C "$VAULT" rev-parse --short HEAD) — $MSG"
if ! git -C "$VAULT" push -q 2>/tmp/brain-commit-push.$$; then
  print -u2 "brain-commit: push failed (brain-sync pushes on its next tick): $(tr '\n' ' ' </tmp/brain-commit-push.$$)"
fi
rm -f /tmp/brain-commit-push.$$
exit 0
