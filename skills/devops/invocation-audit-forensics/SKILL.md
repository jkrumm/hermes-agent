---
name: invocation-audit-forensics
description: Use when a poll loop or cron caller fails silently.
version: 1.0.0
metadata:
  hermes:
    tags: [logs, audit-trail, exit-code, poller, cron, agents, warden, forensics]
    related_skills: [stalled-dispatch-forensics, background-work-watch, warden, agents]
---

# Invocation-audit forensics

An automated caller rarely announces its own failure. It keeps its schedule, writes
one line per attempt into a log nobody reads, and the work it was supposed to collect
simply never shows up — while the surface everyone looks at stays green. This is the
triage for that family: find the caller in the audit trail it leaves, size the
failure, and decide whether the defect is the caller or the thing it calls.

`stalled-dispatch-forensics` asks *is this item progressing*; this skill asks *is the
caller broken*, which is a different answer and usually the missing one.

## Procedure

1. **Find the tool's own invocation log.** The good ones record one line per
   invocation with verb, args, exit code and duration — that is an audit trail, not
   application noise. On this estate: `~/Library/Logs/warden-cli.log` (every warden
   verb), `~/.claude/logs/*.jsonl` (Claude Code hooks), `~/Library/Logs/<service>.{log,err}`
   (LaunchAgents log there, never in `/tmp`).
2. **Group the day's lines by exit code before reading any of them.**

   ```bash
   grep "^$(date -u +%F)" ~/Library/Logs/warden-cli.log \
     | sed 's/.*\(rc=[0-9]*\).*/\1/' | sort | uniq -c
   ```

   A large count of one non-zero code is a **caller defect, not a transient**: a
   usage error (`rc=64`, argparse) fails identically on every tick, so the caller has
   never once succeeded — and the failure stays silent because nothing downstream
   changes.
3. **Read one failing line whole and compare its argument shape with the verb's real
   signature.** The classic shape is one argument too many: `warden status <job-id>`
   takes exactly one id, so a poller batching six ids gets `rc=64` every pass and
   collects nothing while the jobs it polls finish normally.
4. **Walk the process tree to find who is calling it.**

   ```bash
   ps -o pid=,ppid=,lstart=,command= -p <pid>
   ```

   A long-lived `zsh -c …` child of a live agent session is a Bash-tool call whose
   loop never returns; the session's turn is blocked behind it, which is also why
   nothing else has happened in that session.
5. **Recover the work, then stop the leak** — in that order. Read what the caller was
   supposed to read (below) so the run's result is not lost with the loop, then kill
   the looping **shell**, never the agent session: killing the shell returns a result
   to the session's blocked call and lets it continue.

## Collecting results a broken caller orphaned

The common case is a batch whose consumer could not read it, so nobody has. Read each
result directly and report the batch as a summary:

```bash
~/.hermes/scripts/hermes-cc.sh status <job-id>   # status: done + the verdict summary
```

One id per call. A bare `warden dispatch <repo>` episode has **no ledger row**, so
`/board`, `/items/:id` and the gateway log cannot show it — the CLI is the only read.
Summarize by disposition (merge-ready / fix-then-merge / close) with the repo and PR
each verdict names; do not replay twelve transcripts.

## Pitfalls

- **Low CPU proves nothing.** An idle-looking process (0.4 % CPU, sleeping) can be a
  ten-hour call loop; size it from the audit-log line count, never from `ps`.
- **A single correct call next to hundreds of broken ones is usually you.** Before
  reporting a success count, check the timestamps — your own probe lands in the same
  log and mixes with the caller's failures.
- **Attribute the exit code before proposing a fix.** A usage error is the caller's
  bug (fix its argv); a non-zero code with a refusal or error body is the callee's,
  and the refusal text is the finding. Fixing the wrong half leaves the loop running.
- **Do not re-poll, restart or re-dispatch to "unstick" a caller whose jobs are all
  terminal.** Check the jobs first: if every one is `done`, the work is finished and
  only the collection was broken — re-running it duplicates the episodes.
