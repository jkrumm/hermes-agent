---
name: agent-job-evidence-audit
description: Use when auditing what an agent job actually did.
version: 1.0.0
metadata:
  hermes:
    tags: [sideclaw, warden, jobs, evidence, audit, forensics, check, dispatch, sqlite]
    related_skills: [dispatch-liveness-verification, defect-report-verification, warden-lifecycle-gates, status-projection-verification]
---

# Agent job evidence audit

Live surfaces answer "what is it doing now" (that is
`dispatch-liveness-verification`). This skill answers the other question: **what
did it actually do** — after the job is terminal, after its worktree is gone,
when a brief or a card cites a measurement you need to check before relaying.

The projections (Warden's Slack cards, `/board`, the Argo snapshot) and the live
job endpoint are all *renderings*. The durable evidence is two SQLite stores and
one JSONL log, and they outlive every surface that quotes them.

## The three durable stores

| Store | Holds | Path |
|-|-|-|
| sideclaw job store | every `check`/`review`/`dispatch`/`overview` job: params, status, result, error, progress | `~/.local/share/sideclaw/jobs.db`, table `jobs` |
| Warden ledger | items, dispatches (tier, status, verdict, artifact), transitions, operations | `~/.warden/warden.db` |
| sideclaw lifecycle log | `job.create` / `start` / `done` / `fail` / `cancelled` / `recover`, backend selection | `~/Library/Logs/sideclaw.jsonl` |

Read them read-only. On macOS `/usr/bin/sqlite3` has no `-uri`, so open them
from Python rather than the CLI:

```python
import sqlite3, os
con = sqlite3.connect(f"file:{os.path.expanduser('~/.local/share/sideclaw/jobs.db')}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
```

`jobs` columns: `id, tool, params, status, result, error, progress, attempts,
created_at, started_at, finished_at, cancel_requested_at, session_id,
worktree_meta`. `params` and `result` are JSON strings — parse them.

## Procedure

1. **Find the job by content, not by an id you may not have.** `params.cwd` names
the worktree, `tool` the verb, `created_at` the time. Match on the repo path
fragment across the whole table.
2. **Read `result` before `error`.** A terminal job carrying a result is a
finding about the repo; a non-null `error` is a broken run, and the two are
reported differently.
3. **For a `check`, read `result.passed` and every `result.steps[].passed`.** Step
names are canonical (`format`, `lint`, `typecheck`, `test`, `fallow`), and
`result.summary` is one line you can quote verbatim. A step **absent** from
`steps[]` was never discovered — not skipped, not passed.
4. **Separate queue wait from execution.** `elapsedMs` counts from `created_at`,
so a queued job's elapsed time is wait; `started_at` non-null plus a rising
`progress.turns` is execution.
5. **Cross-check the item in Warden's ledger.** The `dispatches` row sharing that
`job_id` carries `tier`, `status`, `verdict_json`, `artifact_url`,
`validation_status`. `triage_items.brief` is the full text the episode actually
received — read it when a card's truncated title is all you have.

## Pitfalls

- **A check result cited against `~/SourceRoot/.hermes-wt/<name>` cannot be
  re-run.** Those worktrees are torn down when the episode ends, so a fresh check
  submitted against that path fails `Directory not found` — a stale path, not a
  repo finding. The job-store row is the only surviving copy: say the result is
  historical, and do not present it as reproducible.
- **`timed out after 180s — likely a watch-mode runner or a hung process` is the
  per-command cap, not a red diff.** sideclaw's `check` caps each command at 180s
  and records the kill as a failed step, so a green-but-slow suite reads red.
  Name the cap when a brief blames the change itself.
- **`Script "<name>" not found in package "<pkg>"` is a half-applied rename, not
  a broken lane.** Renaming a script on one side while a caller still uses the old
  name (a root `--filter <pkg> test`) fails the `test` step on a missing script
  where it previously failed on the cap — which reads as "the fix did not work".
  Grep every caller before concluding anything about the lane.
- **A brief's "measured" claim is a claim.** When a brief asserts a reproduction
  it does not attach, look for the job that would have produced it. If no row
  matches, that direction is unverified — report the counter-direction you *can*
  evidence instead of repeating the claim as fact.
- **`progress.lastAction` is a turn label, not a status.** `turns: 0` with
  `lastAction: starting` is a job that has not begun; a large `turns` with a small
  `idleMs` is one that is working.
- **Do not grep the JSON.** `params` and `result` are single-line blobs; load them
  with `json.loads` and filter in Python, or the job id you are matching on is
  lost in the noise.
