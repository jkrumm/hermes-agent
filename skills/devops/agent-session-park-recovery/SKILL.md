---
name: agent-session-park-recovery
description: Use when a long-running agent session is silently idle.
version: 1.0.0
metadata:
  hermes:
    tags: [agent, session, background, bg, idle, park, quota, limit, revive, resume, herdr, claude-code]
    related_skills: [herdr, wave-chain-execution, background-work-watch, stalled-dispatch-forensics, agent-work-completion]
---

# A silent agent is a parked agent, not a finished one

Use when a long-lived agent — a `claude --bg` orchestrator, a lead pane, a wave
chain — produces no new work while its own ledger still shows an outstanding wave,
item or phase, or when a session shows `idle` and you are about to call it either
*finished* or *waiting on its gate*. Those are different states, and the report
depends on which one it is.

The pane mechanics (explicit ids, never `--current`, `pane run` types into whatever
occupies the pane) are the `herdr` skill; the wave lane on top of it is
`wave-chain-execution`. This file is the question they assume away: **is the session
alive at all, and if it is parked, what revival is correct?**

## Diagnose before you revive

An `idle` status is not evidence. Read the session's transcript tail by absolute
path — `~/.claude/projects/<slugged-cwd>/<session-id>.jsonl` — and compare its last
event with `date`:

| What the tail ends with | What it is | What to do |
|-|-|-|
| `You've hit your weekly limit · resets <time>` and no later turn | **Quota park.** The limit killed the running turn *and the waiter*, so the session is idle and will **not** resume on its own after the reset — not on a mailbox line, not on a heartbeat. | Revive (§ below). |
| a monitor/heartbeat that never fired again, or your own wake-up line with no turn after it | **Dead waiter.** Same revival, but the missing wake-up is the finding. | Revive, then rebuild the wake-up so it survives a killed turn. |
| a question/approval dialog | **Blocked**, waiting on a human. | Hand it to the owner — `ask-human.sh` / the board. Never answer it yourself. |
| a normal turn that ended with a legitimately empty next step | **Parked by design** (a dated exit check, a dependency, a calendar gate). | Do not wake it. Name the date or the dependency and stop. |

Cross-checks, in this order: `claude agents --json` (`kind`, `status`, `cwd` — a
`--bg` daemon shows as `background`); the chain's own ledger/plan for what is
outstanding; the remaining quota.

## Revive, then prove the revival took

1. **Check quota first** — reviving into a fresh limit parks it again immediately.
   `uv run --script ~/.claude/fetch_usage.py` prints nothing; it writes
   `/tmp/claude_sl/usage_api.json` with `five_hour` / `seven_day` `utilization` and
   `resets_at_epoch`.
2. **Revive from a herdr pane, never a bare shell.**

   ```bash
   claude --bg --resume <session-id> "$(cat <brief-file>)"
   ```

   The Max credential lives in the GUI session's keychain: from an ssh session or a
   bare non-pane shell the daemon comes up `Not logged in`, bills the API instead,
   and still looks healthy. If the target pane holds a Claude session, `pane run`
   would type the command into *that* agent's prompt — create a tab for a plain shell
   and close it afterwards.
3. **Expect a clone, not a resume in place.** Resuming a session still listed as
   running prints `session <id> is already running in the background, so this started
   a copy as <new-id>`: follow immediately with `claude stop <old-id>`, or two copies
   of one orchestrator act on the same plan. Say in the brief which id is canonical.
4. **Prove it took a turn**: a new line in the transcript / a `busy` status, not the
   absence of an error. `idle` right after a revive means it accepted no work.
5. **Close the structural gap, not just the incident.** The revival is worth little
   if the same park is silent again: have the session write the exact revive command
   — with its own session id — next to its report channel in the file the next reader
   opens (the plan, `AGENTS.md`), and give the chain a wake-up that fires when the
   prerequisite returns rather than an in-process waiter that dies with the session
   (`prerequisite-gated-cron`).

## Pitfalls

- **The waiter dies with the limit.** An in-process monitor, `tail -F` loop or
  background shell inside the session does not survive the quota kill; treat any
  wake-up that lives *inside* the parked session as unavailable after a park.
- **A `--bg` daemon is invisible where you are looking.** It has no pane and no tab
  in the multiplexer's sidebar, so "no tab open" is not "nothing running". Check
  `claude agents --json` before reporting a build as idle, and say which of the two
  surfaces you checked.
- **A file-mailbox channel needs a proof write.** Before trusting a mailbox/notify
  channel a fleet of workers reports into, have it demonstrated by a write from a
  *second* process and confirm the watcher received it; an unproven channel fails as
  silence, which is indistinguishable from "no news".
- **Never start a second orchestrator to "unblock" a parked one.** Establish exactly
  one canonical session id (stop the inert one) before any revival, and name that id
  in the report.
- **A revival is one model turn.** If the chain has nothing dispatchable, park it and
  say so — spending a turn so it re-derives "nothing to do" is the no-op the owner
  notices.
- **A quota ceiling is a planning input, not a surprise.** A chain that burns ~1 %/hour
  of the weekly window exhausts a week in about four days; read the quota before
  opening a long chain, and keep the worker tier on the off-Max lanes.

## Report shape

Verdict first, in the owner's language: **which park it was** (quota / dead waiter /
blocked / parked by design), since when, what you did, and what was structurally
missing. One line per finding, no narration of the diagnosis. If a decision is now
his, it goes to his queue with the question, not into the reply as an open question.
