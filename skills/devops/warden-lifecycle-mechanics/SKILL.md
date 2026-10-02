---
name: warden-lifecycle-mechanics
description: "Use when a Warden item's brief or state puzzles you."
version: 1.0.0
metadata:
  hermes:
    tags: [warden, dispatch, implement, verdict, ledger, triage, abort, close]
    related_skills: [warden, warden-blocked-items, concurrent-card-dedup, claude-dispatch]
---

# Warden lifecycle mechanics that change your next move

Read-only status is the `warden` skill, blocked-item dispositions are
`warden-blocked-items`, dedup races are `concurrent-card-dedup`. This is the small set of
loop internals that decide what you should *do*.

## The implement episode never reads your item brief

`maybe_auto_implement` (`scripts/triage.py`) opens the implement episode with a **fixed**
brief — "re-read that investigation's own verdict … then implement the fix it described" —
plus `context=_verdict_as_context(item['dispatch_job'], verdict)`: the investigate verdict's
`summary`, `verdict`, `evidence`, `recommendation`, `confidence`, `nextAction`, concatenated
in that order and truncated to `MAX_CONTEXT_CHARS = 16000` (`scripts/lifecycle/dispatch.py`).

- **The item's own `brief` is never passed to the implement episode.** A long, precise
  brief therefore instructs the *investigate* episode only. Anything the implement tier must
  obey — file:line, the corrected remedy, what to preserve — has to be in the investigate
  verdict, which is only ever as good as the brief that produced it. Writing a detailed item
  brief and assuming the implement tier sees it is the failure mode.
- **`evidence` can push `recommendation` past the cap** — the fields concatenate in the
  order above, so a long evidence list silently drops the remedy. Reproduce the exact text
  the implement tier will receive with `~/.hermes/scripts/hermes-cc.sh status <job-id> --json`
  and measure it before trusting it.

## `nextAction: human` skips step-7 validation

An implement episode returning `nextAction: human` moves the item straight to `needs_human`
(`validation_job` NULL, no `review` dispatch) — its diff is never independently validated. A
real regression can therefore reach the owner as "review complete". Read the diff yourself, or
file a bounded fix item, before presenting the ask as reviewed: replaying the change's own
logic against the cases it claims to handle is what caught a crontab write that wiped
unrelated entries.

## `abort` and `close` cover different states, and neither covers the gap

- `abort <event-id>` cancels an **in-flight** episode only; once the job is `done` it refuses
  `job already done` (rc 4).
- `close <event-id>` refuses while the item is `investigating`
  (`an episode or operation is in flight`, rc 2).
- An item whose episode just finished therefore sits in a window where *neither* works: wait
  for the loop's fold to `verdict` (next 600s tick), then `close` it there. A duplicate left
  live in that window takes the repo lock behind the survivor and opens a second stacked PR.

## A claim lives in the dispatch, not always on the item

`item.pr_url` can be NULL while the PR exists: the implement dispatch's `artifact_url` is
authoritative, and an item routed to `needs_human` never had it copied up. Check GitHub
(`gh pr list -R <repo> --state all`) before reporting "no PR" — and read `dispatches[]`, not
just `item.state`, to see every tier a chain has run (investigate → implement → review).
