# Shell script conventions

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

<!-- MOVED-SHELL: moved verbatim from the root AGENTS.md (Shell script conventions, 569 bytes) -->

## Shell script conventions

**Under `set -euo pipefail`, any `$(producer | head -c N)` substitution dies with SIGPIPE (141)
once `producer` exceeds `N` bytes** — `head` closes the pipe, `pipefail` makes the substitution
non-zero, `set -e` ends the script, and the crash happens before the first `echo` so there is no
log line. Guard **inside** the substitution: `$(git diff --cached | head -c 20000 || true)`. Any
new script piping an unbounded producer into `head -c`/`tail -c` under `pipefail` needs it.
The incident it came from: **`docs/shell-conventions.md`**.
