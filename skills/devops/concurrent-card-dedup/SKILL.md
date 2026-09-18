---
name: concurrent-card-dedup
description: "Use when a card may already be carried elsewhere."
version: 1.0.0
metadata:
  hermes:
    tags: [warden, triage, slack, dedup, concurrency, sessions, cards, dispatch]
    related_skills: [warden-item-trail, inbound-notification-verification, claude-dispatch, warden]
---

# One card, several sessions

A Slack card in an agent channel is delivered to **every** session watching that
thread, and each one acts on it independently. Two sessions reading the same
card therefore open two triage items for the same fix, spend two episodes, and
produce two draft PRs against one issue — the loop has no idea they are the
same ask, because each `run` mints a fresh `human:<uuid4>` external id and
nothing dedups on the card.

The tell: several `human:` items on one repo, minutes apart, whose `brief`s are
near-identical prose and whose `payload_json.why` names the **same** upstream
card or issue.

## Before dispatching on a card, check the repo is free

One read, before any `run`:

```bash
curl -s http://127.0.0.1:7735/board \
  | python3 -c 'import sys,json;[print(i["event_id"],i["repo"],i["state"]) for i in json.load(sys.stdin)["items"]]'
```

A sibling item on the same repo in `investigating`, `implementing` or
`validating` means the loop is **already carrying this card**. Do not open a
second one — say the loop has it and stop. The per-repo in-flight lock will
refuse the duplicate anyway, but only after an episode has been spent.

## When a duplicate already exists

1. **Pick the survivor by age and state, not by job id.** The older item with a
   live dispatch wins; the younger one is the duplicate.
   **Exception — superseding briefs.** When the two are the same ask but the
   newer brief *replaces the older one's remedy* (it argues that remedy
   insufficient, or carries the latest decision of a numbered round series),
   keep the newer and abort the older; say the mechanism in the `--why`. Age
   only means "the original, not a re-raise", and it loses to a strictly
   stronger design — keeping the older one ships the weaker fix and buys
   another review round. Decide within the minute: both items are already
   spending episodes, and a survivor left to run twice serializes two
   `implement` episodes into two stacked PRs.
2. **Abort the duplicate, don't close it.** `./scripts/warden abort <event-id>
   --why "Duplicate: item <N> (created <t> from the same card) already covers
   this fix"` — `abort` cancels the in-flight episode and closes the item as a
   side effect. `close` would leave the episode running.
3. **Name the survivor and the mechanism in the `--why`.** The note is the only
   place a later reader learns why two items existed; write it for them, not as
   an apology.
4. **Re-read `/board` immediately before the abort, and never abort into a
   race.** Two sessions deduping one pair at the same time each keep the other
   and abort their own view of the duplicate:
   `A: "1105 is older → abort 1106"` / `B: "1106 has the better brief → abort 1105"`,
   and the repo is left with **zero** carriers. Tell in the ledger: both items
   `investigating → closed` seconds apart, each `note` naming the other as
   survivor.
   - **Keep the oldest live item.** It is the one rule every session can compute
     from the same read, so it converges; the exception above is for a brief
     that is *strictly* stronger, never for "mine".
   - **A session that finds itself the duplicate aborts its own item.**
   - **Aborting an `investigating` episode leaves it terminal with no verdict**,
     which folds to `needs_human` (`investigate episode cancelled with no
     verdict: sideclaw recorded no reason`). That card is the dedup's artifact,
     not a finding — `close` it naming the survivor.
   - **After the abort, re-read `/board`.** No live item on the repo means the
     ask was dropped, not carried: re-open one (`run <repo> --tier implement`)
     with the surviving brief at once.
   - **Expect a herd.** Each re-open spawns further duplicates — three sessions
     opened replacements within 40 seconds of one double abort. Collapse to the
     oldest and stop re-opening.

## Rules

1. **The newest item is not automatically the one to keep.** Re-raises and
   duplicates both land newer than the original; state and a live dispatch
   outrank recency.
2. **A `deferred: repo '<r>' already has an implement episode in flight` note is
   the lock working, not a failure.** That item is parked in `verdict` and the
   loop picks it up on a later tick once the sibling finishes — re-read before
   reporting it as stuck, and never "unstick" it by hand.
3. **Never open a second item to "make sure it happens".** The duplicate costs a
   real episode and a second draft PR against the same issue; the cost of
   waiting one tick is zero.
4. **Report the count, not just the outcome.** "Three items for two cards, one
   aborted as a duplicate" is the finding; a bare "dispatched" hides the waste.
5. **Do not re-dispatch what a sibling already carries.** Same rule as
   `warden-item-trail`: the ledger is the answer, and a card is a snapshot.

## Pitfalls

- **A card delivered into a shared channel is not addressed to one session.**
  Treat "has anyone already opened work for this?" as part of reading the card,
  not as an extra step.
- **A duplicate's own investigation still costs an episode and a job id.** It
  looks like progress in `list open`; it is not.
- **Aborting is not losing the ask — but only while a survivor exists.** The
  survivor carries the identical brief and the aborted item's note is the record
  that the ask was not dropped; if the abort raced another session's (above),
  nothing carries it and the fix is silently gone.
