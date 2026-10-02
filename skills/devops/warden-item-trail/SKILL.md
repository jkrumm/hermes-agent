---
name: warden-item-trail
description: "Use when a Warden card's ask may already be in flight."
version: 1.0.0
metadata:
  hermes:
    tags: [warden, triage, ledger, cards, verification, staleness, re-raise]
    related_skills: [warden, warden-ledger-forensics, status-projection-verification, dispatch-liveness-verification, claude-dispatch]
---

# Warden item trail — one signal, several items

A Warden card is a snapshot written at a transition, and one signal can leave
**several** `triage_items` rows behind it: the ingest, a row dismissed as a test
fixture, one aborted for the wrong tier, and the re-raise that is actually live.
The newest row is usually the re-raise, and its `brief` is the *loop's own*
earlier verdict text quoted back — so answering from the card, or from the newest
row alone, reports a proposal as outstanding work.

Use this before telling Johannes a triage card needs him, and before relaying a
card's proposed next action. It is the ledger half of
`status-projection-verification`; `warden` owns the endpoints.

## Procedure

1. **Read the card's item, then leave the card.** `GET /items/<event_id>` —
   `item.state`, `item.max_tier`, `dispatches[].status`, `item_transitions`.
2. **Resolve the signal to every row it produced.** Join the source object to the
   ledger and order by row:

   ```python
   # ~/.hermes/hermes-agent/venv/bin/python3 — never the /usr/bin/sqlite3 CLI
   import sqlite3
   con = sqlite3.connect("file:/Users/<user>/.warden/warden.db?mode=ro", uri=True)
   con.execute("select event_id, state, max_tier, note from triage_items"
               " where repo=? order by event_id", (repo,))
   con.execute("select from_state, to_state, at, note from item_transitions"
               " where event_id=? order by id", (event_id,))
   ```

   `events.external_id` (`owner/repo#n`) is the stable join key; `dispatches`
   joins to the item by `origin_event_id`, not `event_id`.
3. **Check the source object itself.** For an issue:
   `gh issue view <n> --repo <owner>/<repo> --json state,stateReason,comments` —
   a hand-written closing comment is authoritative and invisible in every
   projection, and it is where a dismissal reason lives.
4. **Decide, then report one of three dispositions** — already landed, already
   in flight, or genuinely open — and lead with it.

## Rules

1. **A card carrying a proposed `nextAction: implement` is a proposal, not a
   to-do.** Before relaying it as outstanding work, check whether a sibling row on
   the same repo is already live (`investigating`/`implementing`) with a job id.
2. **A wrong-tier abort is self-healing, and fast.** The loop closes an item whose
   tier can never land the fix and re-raises a sibling at the right tier within
   seconds, so a card read a minute later is already obsolete. "The loop is
   already carrying it" is the answer; never offer a snooze or a re-dispatch for
   work in flight.
3. **A card's "investigation running — job …" line is rendered from the item's
   state, not the job's status.** Confirm the job actually started before saying
   anything is running — see `dispatch-liveness-verification`.
4. **A docs-only gap is verifiable from the repo, not from the verdict.** Diff
   `package.json`'s `scripts` against the README section the card names before
   agreeing the gap is real; a verdict can be right about the gap and wrong about
   what is already documented elsewhere in the file.
5. **Answer the status question and stop.** No re-dispatch, no snooze, no
   "should I…" — the ledger plus the source object is the whole deliverable.

## Report shape

Verdict first, in German, three to five lines: what the card claims, what is
actually true now, and the one thing that changes his next move (usually
nothing). Name the mechanism — the tier ceiling, the dismissal, the queue — not
the state name.
