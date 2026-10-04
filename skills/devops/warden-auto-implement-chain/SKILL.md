---
name: warden-auto-implement-chain
description: Use when a Warden verdict should become a fix on its own.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, triage, auto-implement, lifecycle, verdict, github-issue, reporting]
    related_skills: [warden, warden-item-watch, warden-verdict-disposition, claude-dispatch, dispatch-liveness-verification]
---

# Warden's auto-implement chain

A verdict that says "implement this" is not a question for Johannes. For an item
the loop is allowed to act on, Warden **claims it and opens the implement episode
itself** — no Slack click, no `dispatch --tier implement`, no approval. Your job is
to recognise that moment, say the fix is in flight, and report the PR when it
lands.

Reading an item is the `warden` skill; watching any item to its terminal state is
`warden-item-watch`; a verdict the loop will *not* consume is
`warden-verdict-disposition`. This skill is the middle case: the chain that runs
without anyone.

## The eligibility gate (all four must hold)

`maybe_auto_implement()` in `~/SourceRoot/warden/scripts/triage.py` picks up an item
when, at a loop tick:

1. `state = 'verdict'` and `dispatch_job IS NOT NULL` and `implement_job IS NULL`,
2. `max_tier = 'implement'` on the item,
3. the folded investigate verdict reads `nextAction: implement`, and
4. `confidence: high`.

`max_tier` is set at ingest: a GitHub issue **authored by the owner** gets
`implement`; anyone else's gets `investigate` and can never reach this chain.

## Procedure

1. **Read the item, not the card.** `curl -s http://127.0.0.1:7735/items/<event_id>`
   → `item.state`, `item.max_tier`, `item.implement_job`, `dispatches[].verdict`,
   `transitions[]`, `operations[]`.
2. **Read the verdict's own fields, not its prose.** `nextAction` and `confidence`
   are what the loop branches on; `summary`/`recommendation` are for your report.
3. **If the four gates hold, the loop owns it.** Report it as in flight in the
   first reply — do not offer a dispatch, do not present the verdict as a decision,
   do not ask for an approval. A GitHub-issue-sourced item needs no click.
4. **Poll through `verdict`.** The claim lands on the next tick (the loop is a
   600 s LaunchAgent), so the item sits in `verdict` for minutes after the
   investigate job reads `done`. `verdict` is a *transient* state here, not an
   outcome — a watch loop that stops on it reports a finished investigation as the
   result of work that has not started.
5. **Report the artifact, once.** `item.pr_url` plus what the diff changed. Read
   the diff (`gh pr diff`) rather than repeating the episode's own summary.

## State sequence and what each step means

`investigating → verdict → implementing → validating → merged → liveness_pending → fixed`

- `verdict` → `implementing` is the claim: a compare-and-set `UPDATE` that also
  records `implement_job`. `operations[]` carries `authorized_by: auto-from-item`
  — that string is the proof no human approved it.
- `implementing` has a 2 h deadline that expires to `merge_blocked` if no
  `implement_job` ever shows up.
- `validating` is a **different model** reviewing the diff; `merged` only follows
  when the repo's own `autoMergePaths` in `config/triage-policy.json` covers every
  changed path.

## Pitfalls

- **Do not promise a merge.** `repos` in `config/triage-policy.json` lists only the
  repos with an `autoMergePaths` entry; a repo absent from that map can never
  auto-merge, however clean its validation. Its PR stays a draft for Johannes to
  review — say exactly that instead of "it will land".
- **`hermes-cc.sh status <job-id>`'s `ok` field describes the job, not the call.**
  A running job answers `ok: false` with `status: running`; a finished
  lifecycle job answers `ok: true` with `repo`/`tier` as `-` and the verdict
  present. Read `status` and `verdict`, never `ok` alone.
- **A repo capped below `implement` is not a deferral.** The loop writes
  `needs_human` with "apply the fix by hand" and stops trying — that card is
  correct, and re-dispatching the same repo refuses again. Hand it to
  `warden-verdict-disposition`.
- **Never re-dispatch a verdict the loop is already acting on.** One item, one
  episode per stage; a duplicate burns a session for the same answer.
- **The verdict's `recommendation` is a claim, not a finding you verified.**
  Quote it as the episode's conclusion, attribute it, and let the implement
  episode's diff be the evidence.
