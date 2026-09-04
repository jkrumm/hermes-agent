# Shell script conventions

Moved verbatim out of `CLAUDE.md` (2026-09-04, size pass). `CLAUDE.md` § Shell script conventions points here — nothing was rewritten, only relocated.

**Under `set -euo pipefail`, any `$(producer | head -c N)` substitution dies with
SIGPIPE (141) once `producer`'s output exceeds `N` bytes** — `head` closes the pipe
early, `producer` gets SIGPIPE, and `pipefail` turns the whole substitution non-zero,
which `set -e` treats as a script-ending failure. This bit `dotfiles/brain/brain-backup.sh`
in production: a `PROMPT="$(git diff --cached | head -c 20000)"` line aborted the nightly
job before its commit, on the first diff over 20 KB, with no log line at all (the crash
happens before the first `echo`). Guard the truncation **inside** the substitution, not
after the whole assignment: `$(git diff --cached | head -c 20000 || true)`. A sibling
line guarded the same way (`| tail -1 ... || true`) never tripped. Any new script here
piping an unbounded producer into `head -c`/`tail -c` under `pipefail` needs this guard.
