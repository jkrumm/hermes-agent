---
name: dispatch-liveness-verification
description: Use when checking if a dispatched agent job is running.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, sideclaw, dispatch, liveness, verification, queue, projection]
    related_skills: [warden, agents, claude-dispatch, agent-session-reporting]
---

# Dispatch liveness — verify at the executor, never at the projection

Every human-facing surface in this estate is a **projection** rendered from
ledger columns: Warden's Slack cards, `GET /board`, the Argo snapshot, the
agents overview. None of them knows whether the episode is actually
executing. The executor is **sideclaw**, on its own loopback door:

```bash
curl -s http://127.0.0.1:7705/api/jobs          # every job, newest first
curl -s http://127.0.0.1:7705/api/jobs/<id>     # one job: status, startedAt, progress
curl -s http://127.0.0.1:7705/api/jobs/health   # {ok, running, pending, max, oldestPendingAgeMs}
```

Use `127.0.0.1`, and remember the MCP process is a *separate* process from the
HTTP server that owns the jobs — polling the HTTP door is what sees durable
state.

## Procedure

1. **Get the job id from the projection**, then leave the projection. `/board`'s
   `dispatch_job`, `/items/<id>`'s `dispatches[]`, or the card's `job <8 chars>`
   line all carry it.
   - **Expand a shortened id against `GET /api/jobs` before querying it.** The
     executor's single-job door matches the **full uuid only**: a card's
     `job cff0120c` (or any prefix) answers
     `{"ok":false,"error":"job not found"}` — which reads exactly like a job that
     never existed. Look the prefix up in the full listing, then query the uuid.
2. **Ask sideclaw what the job is doing.** `status`, `startedAt`, `progress`.
3. **Interpret against the queue, not in isolation.** `GET /api/jobs` shows what
   occupies the slots; `jobs/health`'s `oldestPendingAgeMs` shows how long the
   backlog has waited.
4. **Report the verdict first**: running / queued behind X / stuck — then the
   job id, its status, what is ahead of it, and the oldest wait.

## Pitfalls

- **`pending` with `startedAt: null` means the episode has NOT started.**
  sideclaw admits `SIDECLAW_JOB_CONCURRENCY` (default 3) at a time and queues the
  rest. Saying "an investigation is running" for a queued job is the single most
  common way this report goes wrong.
- **Two caps, independently enforced, neither aware of the other.** Warden's
  `MAX_OPEN_INVESTIGATIONS` counts items in state `investigating`; sideclaw's
  concurrency cap counts executing jobs. An item can therefore be
  `investigating` with a real job id while that job waits behind a long `review`
  or `dispatch` — a state that looks like progress and is not.
- **A card's "Investigation running — job …" line is rendered from the item's
  state, not the job's status** (`state == investigating AND dispatch_job IS NOT
  NULL`). It reads "running" for a job that has not started. Never repeat it
  without checking `/api/jobs/<id>`.
- **`note` is not cleared on every transition, so it can describe a state the
  item has already left.** Queue/deferral text written while an item was `new`
  (`queued: at MAX_OPEN_INVESTIGATIONS=…`, `deferred: …`) survives the
  `new → investigating` claim, because the escalation writes `dispatch_job`
  without passing `note=`. `/board`, the Argo snapshot and the item payload
  relay the column verbatim. **Read every `note` against its `state`**; when the
  two disagree, name which one is stale instead of repeating either.
- **A long queue is not a hang.** The only real stuck signal is
  `progress.idleMs` large *and still growing*; a large `elapsedMs` on a `review`
  or a `dispatch` is normal. Name the job ahead of it before calling anything
  hung, and never kill or restart a job to "unblock" a queue.
- **A dispatch with no verdict is not a verdict.** A terminal job that returned
  no result folds to `needs_human` carrying `dispatches.error` — read the error,
  not the state name.

## Report shape

Verdict first, in German, one line per finding: what the job is doing, what is
ahead of it, how long the oldest has waited, and — only if it changes his next
move — the stale `note` or the cap that produced it. No PID dumps, no
step-by-step narration of the calls you made.
