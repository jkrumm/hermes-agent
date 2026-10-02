---
name: terminal-command-hygiene
description: Use when composing shell commands for the terminal tool.
version: 1.0.0
metadata:
  hermes:
    tags: [terminal, shell, quoting, heredoc, payload, exit-code, pgrep, process, hygiene]
    related_skills: [background-work-watch, devhost-maintenance]
---

# Terminal command hygiene

How to compose commands for the `terminal` tool so they do what you meant, and how
to read their output honestly: multi-line payloads, quoting hazards, pipe and exit
codes, per-command env scoping, long/interactive jobs, process cleanup. Load this
before any command that pipes into an interpreter, embeds a multi-line body, or
starts a long-running job. Every rule here has already cost a session real damage
or a wrong conclusion.

## Multi-line payloads go in a file, never in an inline heredoc

```bash
# WRONG — the harness wraps the command; the quoting is lost and any backticked
# fragment inside the body is EXECUTED as shell. This has launched a stray
# mass-upgrade and nearly filed a garbage issue.
gh issue create --body "$(cat <<'EOF'
…`make something`…
EOF
)"

# RIGHT
# 1) write_file('/tmp/payload.md', '…')
gh issue create --body-file /tmp/payload.md
curl -X POST --data-binary @/tmp/payload.json …
```

Same rule for JSON bodies and commit messages (`-F body=@file`, `-F files[]=@file`).
The file is data, so backticks, `$` and quotes in it are inert. Read the created
object back once (print the returned id/url) — an argument that never reached the
tool looks identical to one that was rejected.

## Pipe traps

- **A pipe hides the real exit code.** `cmd | tail -3` returns *tail's* status, so a
  failure reads as `exit_code 0`. When the exit code is the point, do not pipe —
  output is auto-truncated and the full text is saved to a file anyway. If you must
  parse, write to a file first and parse the file.
- **Do not pipe JSON into `python3 -c`.** Use `curl -s -o /tmp/x.json …` then a
  separate `python3 -c` that opens the file; a piped stream trips the interpreter
  scan and swallows the error into a `JSONDecodeError` traceback.
- **`pgrep -f` matches its own pattern.** Bracket the first character
  (`pgrep -fl "[b]rew.rb"`) when the check runs from the same shell.

## Scope environment per command

- Prefix, never export: `GIT_TERMINAL_PROMPT=0 git push`, not a preceding `export`.
  Session exports leak into later calls that must not inherit them (a left-behind
  `GIT_DIR`/`GIT_WORK_TREE` retargets every later git command).
- Same rule for a target needing a non-login PATH, in ONE command:
  `export PATH="$HOME/.bun/bin:$PATH"; make <applier>`.
- macOS `sqlite3` has no `-uri`: use python
  `sqlite3.connect('file:…?mode=ro', uri=True)` for read-only access to a live DB.

## Long and interactive jobs

- Bounded but slow → `background=true, notify=true`, then `process(action='wait')`.
- Interactive (`apply? [y/N]`) → `background=true, pty=true`, read the prompt and the
  review material out of the process output, then
  `process(action='submit', data='y')`. Never reach for a skill's env-var bypass to
  skip a review gate.
- Before starting any mass/locking job, check whether one is already running
  (`pgrep -fl`, the unattended log dir) — the second run spins at ~100% CPU on the
  incumbent's locks.
- Cleanup: `kill -TERM <pids>`, verify, `kill -9` only for what ignored it, then
  re-`pgrep`. Report the PIDs you killed only when they evidence the fix.

## Reading a tool result

An `exit_code: 0` next to a stack trace is the *pipeline's* status, not the
command's — treat any run whose output contains failure indicators as failed until
re-run without the pipe. Same for "no output": silence from a filter is not silence
from the tool.
