---
name: dispatch-round-refiling
description: Use when a verdict must become the next dispatched round.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, dispatch, verdict, refile, brief, implement, handoff]
    related_skills: [warden-verdict-disposition, dispatch-brief-authoring, claude-dispatch, warden]
---

# Refiling a verdict as the next round

A finished `investigate` episode is a claim plus an opinion, and the item it landed
on is parked. Warden's loop consumes exactly ONE verdict shape —
`nextAction: implement` at `confidence: high`, with the repo's ceiling allowing it.
Everything else sits in `verdict` with nothing polling it and decays to
`needs_human` on its 24 h deadline, where the card reads like a fresh ask. Deciding
whether that parked verdict is *yours to execute* or *the owner's to weigh*, and
then opening the next round correctly, is this skill.

Discharging and closing the old item is `warden-verdict-disposition`; the episode
verb and its gates are `claude-dispatch`; brief craft is `dispatch-brief-authoring`.

## 1. `human` is not automatically "wait for the owner"

`human` is the fold for *every* verdict the loop could not auto-implement, so it
covers two very different cases. Read the `recommendation` before treating it as an
ask:

- **It names a bounded change** — a function, a path, a few lines, a named seam.
  The episode has already made the call; it asked for confirmation, not for a
  decision. Re-file it yourself and close the old item naming the new one. Parking
  this is how a decided finding sits for a week and then arrives as "work for you".
- **Two readings carry materially different blast radius** — a semantics or policy
  change that alters behaviour everywhere, a public surface, a cost. That one is the
  owner's: surface it with the recommendation attached and let the `needs_human` row
  be the record.

Same test for `none` / `issue`: neither means the item is done or that an issue
exists, only that you own the disposition.

## 2. The brief for a re-filed implement round

```bash
env -u CLAUDECODE ~/.hermes/scripts/hermes-cc.sh run <repo> --tier implement \
  --why "<what was confirmed, and why a write episode is authorised>" \
  --origin-channel "$SLACK_CHANNEL" --origin-thread "$SLACK_THREAD_TS" --json \
  < brief.txt
```

- **It runs its own `investigate` first.** `run --tier implement` does not go
  straight to a writer; a brief phrased as a fix order is re-derived from scratch by
  that fresh investigate and can come back about a different question entirely.
- **So the brief carries: the confirmed mechanism → the chosen semantics → the
  question the fresh investigate must answer.** End on that question ("is this the
  right seam — and if so make the change"). Stating the mechanism is what keeps the
  second episode from re-litigating the first one's evidence.
- **Name the boundary.** Say which function or path is in scope and which existing
  behaviour must not move (the other caller, the explicit-override path), or the
  implement round widens the change on its own judgement.
- **The brief is data** — stdin, quoted heredoc or a file, never argv; a long brief
  belongs in a file. Never a secret, never a path where a repo name will do.

## 3. What re-filing authorises

**`run --tier implement` needs no Slack click.** Warden's own lifecycle goes from a
`high` implement verdict straight into `implementing`; only the bare `dispatch`
verb sits behind Approve/Deny. So re-filing *is* authorising a write episode, and
the repo's own merge policy is the last human gate — a repo in `merge_approval`
ends in a draft PR the owner merges himself, one without stays a draft forever.
Re-file when the verdict named the change; do not use it to launder a decision the
owner has not made.

## 4. Verify the round you opened, then close the one you replaced

- **The new episode's base OID, before you trust its answer.** Read the job's
  `dispatch.worktree` line in `~/Library/Logs/sideclaw.jsonl`: read tiers cut at the
  live checkout's `HEAD`, so a repo whose work is pushed from agent worktrees can
  hand the new episode the same stale tree that produced the first wrong verdict.
  Fast-forward first when it lags, and say which tree the round actually read.
- **Confirm the item exists and is running** — `curl -s
  http://127.0.0.1:7735/board` (the new `event_id`, its `state`, its `dispatch_job`),
  and the job's own status at `http://127.0.0.1:7705/api/jobs/<uuid>` — `pending`
  with a `startedAt: null` is queued, not running.
- **Close the old item naming the new one**, so the parked card cannot present
  itself as outstanding work later, and the chain is traceable from either end.

## Pitfalls

- **A note is a claim, not evidence.** An item's `note` — "follow-up armed as cron
  X", "tracked in issue Y", "verified independently" — is written by whichever lane
  closed the item and is append-only. Check the named artifact (`~/.hermes/cron/
  jobs.json`, `gh issue view`) before repeating it or building on it; a guard that
  was never created leaves the work it was meant to release parked, and a note
  written on a stale tree asserts the opposite of the truth.
- **Another lane may already have done it.** A peer Hermes session's own calls are
  readable in `~/.hermes/state.db` (`messages`, by session id); the ledger carries a
  `closed by hand:` row with a timestamp in `triage_items.note` /
  `item_transitions`. Search the item id there before contradicting or redoing a
  sibling lane's work — two lanes each closing the other's round ends with zero
  episodes and no fix on the way, which is worse than a duplicate.
- **A failed implement episode disqualifies an item from auto-implement for good**
  (`maybe_auto_implement()` requires `implement_job IS NULL`). The stale
  `implement_job` is the tell, not the verdict text — re-file as a new item rather
  than trying to un-stick the old one.
