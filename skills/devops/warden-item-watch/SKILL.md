---
name: warden-item-watch
description: "Use when watching a Warden item to its terminal state."
version: 1.0.0
metadata:
  hermes:
    tags: [warden, dispatch, lifecycle, polling, background, reporting, item]
    related_skills: [warden, claude-dispatch, dispatch-liveness-verification, stalled-dispatch-forensics]
---

# Watching a Warden item

An item opened by `run`, or ingested from a GitHub issue, rides Warden's own
lifecycle — `new → investigating → verdict → implementing → validating → merged
→ liveness_pending → fixed`, with `needs_human`, `merge_blocked`, `closed` and
`dismissed` as off-ramps. You are not driving it. Your job is to know which
state it is in, say only what changes Johannes's next move, and report the
outcome once — not every state change in between.

Reading the item is the `warden` skill; the queue mechanics behind a slow step
are `dispatch-liveness-verification`; a genuinely wedged job is
`stalled-dispatch-forensics`. This skill is the *watch*: the poll loop, the exit
condition, and the reporting discipline.

## Procedure

1. **Read the live item, not the card.** `curl -s http://127.0.0.1:7735/items/<event_id>`
   gives `item.state`, `item.pr_url`, `item.note`, `dispatches[]` (one row per
   stage, each with its own `job_id` and `verdict`) and `transitions[]`.
2. **Decide whether it needs a human at all.**
   - `investigating` / `implementing` / `validating` — the loop working. Needs
     nobody; say so in one clause and let it run.
   - `needs_human` / `merge_blocked` — the only two that want Johannes. Lead with
     the `note`, which is *why* it stopped, not the state name.
   - `merged` / `fixed` / `closed` / `dismissed` — terminal, report the artifact.
3. **Watch it in ONE tracked background process** (see below) rather than
   polling in the turn. A validation step behind a full queue legitimately takes
   10–20 minutes; an `implement` episode 10–40.
4. **Verify the artifact yourself before calling it done.** Read the diff, not the
   verdict's summary of it:

   ```bash
   gh pr diff <n> --repo <owner>/<repo>
   gh pr view <n> --repo <owner>/<repo> --json state,mergedAt,mergeable
   ```

   An episode's `summary` is its own self-report; the diff and the PR's `state`
   are the facts.
5. **Report once, at the outcome.** PR link plus what it changed, or the reason it
   stopped. Then stop talking about it.

## The watch loop

```bash
# terminal(background=True, notify=True) — the loop IS the tracked process
for i in $(seq 1 60); do
  s=$(curl -s http://127.0.0.1:7735/items/<event_id> | python3 -c "import json,sys;i=json.load(sys.stdin)['item'];print(i['state'], i['pr_url'] or '-')")
  echo "$(date -u +%H:%M:%S) $s"
  case "$s" in merged*|fixed*|needs_human*|merge_blocked*|closed*|dismissed*) break;; esac
  sleep 60
done
```

- **A foreground `for … sleep …; done` dies at the terminal tool's timeout** and
  is yielded mid-loop, so the result is lost. **A `nohup … &` inside a background
  call returns instantly**, so the completion notice fires before the loop has
  done anything. Run the loop directly as the background command.
- `(eval):1: can't change option: zle` in the output is zsh noise from the
  non-interactive shell, not a failure.
- **Never re-dispatch because a poll looked slow.** One item, one episode per
  stage; a duplicate burns a session for the same answer.
- A `validating` item whose job sits `pending` is queueing, not broken — check
  `curl -s http://127.0.0.1:7705/api/jobs/health` (`running` vs `max`, default 3)
  before saying anything about it.

## Pitfalls

- **`hermes-cc.sh status <job-id>` cannot resolve a lifecycle job.** A step-7
  validation is recorded with `tier: review`, which the CLI's `status` verb does
  not map, so its stored verdict stays empty and a job that is genuinely running
  reads as `status: pending`, `ok: false` — indefinitely. For anything reached
  through the lifecycle, the authority is sideclaw's `GET /api/jobs/<id>`
  (`status`, `startedAt`, `progress`). Only a bare `dispatch` episode is
  faithfully reported by `status`.
- **Do not narrate the middle.** "Implement-Episode läuft" is not an outcome. He
  hears from you when the PR exists, when the item needs him, or when it failed —
  a running state is silence plus a one-line acknowledgement if he asked.
- **A `note` is a snapshot from the last transition**, and the work can land while
  a card is still in flight. Before relaying a `needs_human`/`merge_blocked` note
  as outstanding work, check the repo's `git log` and the live state of whatever
  the note named.
- **A GitHub-issue-sourced item needs no Slack click.** `operations[]` carries
  `authorized_by: auto-from-item`; the loop proceeds on its own once the verdict
  is confident and the repo's policy allows the tier. Never tell Johannes an
  approval is pending for one.
- **A repo capped at `investigate` ends a confident `implement` verdict at
  `needs_human`** with "apply the fix by hand" — that is the policy working, not a
  failure to route around.
