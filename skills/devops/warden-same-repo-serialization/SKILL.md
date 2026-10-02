---
name: warden-same-repo-serialization
description: "Use when two Warden items target the same repo."
version: 1.0.0
metadata:
  hermes:
    tags: [warden, dispatch, implement, lock, concurrency, lifecycle]
    related_skills: [warden-item-watch, claude-dispatch, warden-verdict-disposition]
---

# Same-repo dispatch serialization

Warden holds **one implement episode per repo at a time**. The lock covers the
`implementing` and `validating` states, checked both on the triage item and on
the operations ledger, so a second `run <repo> --tier implement` opened while the
first is still writing does not start writing — it sits in `investigating`, or
comes back `queued: true`, until the first clears.

That is the design working, not a stall. When you see it:

- Do not re-dispatch the parked item, and do not `abort` the in-flight one to
  unblock it — aborting discards the work the lock is protecting.
- When you tell Johannes about two fixes for one repo, say they land one after
  the other, not in parallel. Do not imply concurrency you do not have.
- `investigate`-tier items are unaffected; the lock is on the write states only.

## Polling without losing the snapshot

Watch an item by polling `GET /items/<event_id>` in **short intervals** (a minute
or two per call), reading `transitions[]` and the stage job's `status`/`progress`
from `GET /api/jobs/<id>`. A single multi-minute `sleep` inside a foreground call
is killed before it returns and the snapshot is lost; short polls survive and let
you tell a slow episode from a stuck one.

## Replacing a stale `needs_human` card

A `needs_human` card citing a repo tier cap can be stale: the cap is a policy
value in `config/dispatch-repos.json`, and nothing re-evaluates an already-parked
item when it changes — the card keeps its old note until expiry. Re-run the gate
yourself (`resolve_tier('implement', resolve_repo('<repo>'))` from warden's venv,
plus `make check-policy`); if it now passes, `close` the stale item naming the
lifting commit and open the work fresh with `run <repo> --tier implement`, reusing
the old item's `nextAction: implement` verdict as the brief. The replacement then
rides the lifecycle on its own — and if another item for that repo is mid-write,
expect it to wait in `investigating` per the lock above.
