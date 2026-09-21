---
name: warden-card-intake
description: Use when an inbound Warden card names an ask.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, cards, triage, slack, pollers, cadence, timing, ticks, disposition]
    related_skills: [warden, warden-item-trail, warden-item-watch, concurrent-card-dedup, warden-lifecycle-gates, dispatch-liveness-verification, background-work-watch]
---

# Warden card intake

A card is a **projection written at one transition**, delivered to every session
watching the thread. Arriving at one is not a trigger to dispatch: it is a trigger
to resolve the card to its live item, read the item's current state, and answer
with what is true now **plus which poller tick moves it next**. Neighbour skills
own the deeper dispositions — duplicate carriers `concurrent-card-dedup`, a stale
ask `warden-item-trail`, the gate behind a stop `warden-lifecycle-gates`, the wait
itself `background-work-watch` — this skill owns the intake step and the cadence.

## Procedure

1. **Join the card to its item.**
   - The `human:human:<uuid4>` in the card body is `triage_items.signature`; the
     same string is on the `/board` row and in `/items/<event_id>`'s `item`.
   - `/items/<event_id>`'s `item.card_ts` is the Slack ts of the card itself, so a
     card whose header names no event id is still pinned exactly by matching
     `card_ts` (or repo + title, when it is not this card's thread).
   - `item.origin_channel` + `item.origin_thread_ts` are where the loop delivers
     the verdict. When they name a different thread than the card's, the sweeper
     already answers there — do not promise a relay that lands elsewhere.
2. **Read the live item, never the card's claim.**
   `curl -s http://127.0.0.1:7735/items/<event_id>` → `item.state`, `max_tier`,
   `dispatch_job`/`implement_job`/`validation_job`, `transitions[]`, and every
   `dispatches[]` row with its own verdict. `item.brief_truncated: true` means the
   row carries a capped copy of the brief — the episode got the full text, so do
   not "restore" it or treat the cut as a defect.
3. **Check the repo is free before opening anything.** `curl -s
   http://127.0.0.1:7735/board` — a sibling item on the same repo in
   `investigating`/`implementing`/`validating` is already carrying the ask. Say the
   loop has it and stop; a second item spends a real episode and a second draft PR
   against one issue.
4. **Confirm the job started at the executor** before repeating "running":
   `curl -s http://127.0.0.1:7705/api/jobs/<id>`. The card's "Investigation
   running — job …" line is rendered from the item's columns, not the job's
   status, and is true for a job still `pending`.

## Answer the card, not the card's ask

- **An item already `investigating`/`implementing` needs nothing from you.** The
  loop opened it, folds the verdict itself, and opens the next stage itself. Say
  that in one clause and stop: no `run`, no approval, no snooze, no "soll ich …?".
- **Only `needs_human` and `merge_blocked` want a person.** Lead with the `note`,
  which is *why* it stopped, not the state name.
- **The next stage is not yours to open.** An item whose `max_tier` is `implement`
  and whose investigate verdict returns `nextAction: implement` at
  `confidence: high` gets its implement episode opened by the loop on a later tick
  — no Slack click, no re-dispatch from you. `max_tier: investigate` never reaches
  that stage at all; a confident implement verdict there is routed to
  `needs_human` as a hand-fix.
- **The merge is the owner's whenever the repo has no `autoMergePaths`.** A repo
  absent from `config/triage-policy.json`'s `repos` is never auto-mergeable, so
  "draft PR open and verified, awaiting your merge" is the finished report — never
  merge around it (`warden-lifecycle-gates`).

## The cadence — every transition is tick-bound

An item's state advances only **inside a poller run**; an episode finishing does
not move it.

| Poller | LaunchAgent | Interval | it owns |
|-|-|-|-|
| loop | `com.jkrumm.warden-loop` (`triage.py --run`) | 600 s | folds a landed verdict into `verdict`, opens the next stage's episode |
| dispatch sweep | `com.jkrumm.warden-sweep` | 300 s | folds dispatch results into the item |
| ingest poll | `com.jkrumm.warden-poll` | 1800 s | new events → `triage_items` |
| api | `com.jkrumm.warden-api` | long-running | `/health`, `/board`, `/items/<id>` |

`GET http://127.0.0.1:7735/health`'s `pollers.<name>.last_run` / `age_minutes`
against that interval is the ETA — one read, no guessing.

- **A state younger than one tick is normal, not stuck.** A `verdict` row waiting
  for its `implementing` transition, or an `implementing` row whose job has not
  appeared yet, is simply between ticks: the verdict folds on a sweep, and the
  implement episode opens on a later loop tick — minutes apart, on an item that is
  progressing perfectly.
- **Never hold the turn open for a tick-bound transition.** A foreground poll is
  cut at the tool's ceiling long before a 10-minute tick fires, and the item will
  not move any faster for the watching. Compute the tick, state it in the reply,
  and hand any real watch to a tracked background loop.
- **`--wait` does not bound an episode.** It blocks ~170 s while an `investigate`
  episode can run several minutes even on a clean run, so a `--wait` timeout means
  the verdict arrives later through the sweeper — not that the episode failed. A
  longer watch polls by job id (`status <job-id>`; the lifecycle review tier is not
  mapped by that verb, so read those at the executor instead).
- **`pollers.*.ok: false`** (age > 3× its interval) is the real "the loop stopped"
  finding. An item sitting still is not one.

## Pitfalls

- **A card's title is the loop's own prose, often a verdict quoted back.** Read the
  item's state and `dispatches[]`, and never relay a card's proposed next action as
  outstanding work before checking whether a live sibling already carries it.
- **Two cards from one incident are not two asks.** Recovered monitors and the
  service-level item they belong to land as separate rows (repo empty on the
  monitor ones); unclaimed `new` monitor cards resolve by silence, so they are not
  work you need to route.
- **Do not re-file, re-dispatch or "unstick" to make an in-flight item finish.**
  The only re-dispatch worth considering is after a gate that needs a *different*
  tier, and that decision is `warden-lifecycle-gates`', not this step's.
- **A `human` item's brief can be implement-shaped while its `max_tier` is
  `investigate`.** `warden run` defaults to `investigate`, and the only trace of
  the caller's intent is the item's title (`flags.why` — `--why` is required
  *only* for `implement`), so a `why` present with `max_tier='investigate'` means
  the tier flag was dropped on the way in. Such an item can never implement: a
  high-confidence `implement` verdict folds straight to `closed` with
  `answered: <summary>`, because `fold_dispatch_verdict()`'s `max_tier` branch
  fires before `maybe_auto_implement()`'s eligibility query ever sees the row.
  Re-file it as `run <repo> --tier implement --why <same text>` — a replacement,
  not the duplicate `concurrent-card-dedup` warns about — and the loop opens the
  implement episode itself on its next tick, once the new item's own investigate
  verdict folds.

## Report shape

Verdict first, German, 3–6 lines: what the card claims, what is true now, which
poller tick moves it next, and the one thing that changes his next move (usually
nothing). Name the mechanism — the tick, the gate, the repo lock — not the state
name. No step-by-step narration of the calls you made, and no closing question
about work the loop already owns.
