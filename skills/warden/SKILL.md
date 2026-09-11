---
name: warden
description: Read-only status over Warden, the deterministic control plane that triages, decides and dispatches Claude Code episodes. Use for "what is warden doing", "what needs me", "what happened to item N", "is the loop healthy", "was macht warden gerade", "hängt was fest", or any question about the state of an item, a dispatch, or the loop's own liveness.
version: 1.0.0
metadata:
  hermes:
    tags: [warden, triage, ledger, board, control-plane]
    related_skills: [claude-dispatch, agents]
---

# Warden — read-only status over the control plane

Warden (`~/SourceRoot/warden`) is the deterministic control plane: it ingests
signals, decides, dispatches Claude Code episodes through sideclaw, and owns
the only ledger (`~/.warden/warden.db`) — five LaunchAgents, no LLM call
anywhere in the loop. Handing it work is **`claude-dispatch`**'s `run` verb;
this skill only reads what it's doing back, over its loopback HTTP API.

**This skill is READ-ONLY**, same shape as `agents`. It never opens an item,
merges a PR, or aborts a run — that's `claude-dispatch`.

## Always `127.0.0.1`, never `localhost`

`http://127.0.0.1:7735` — loopback only, no auth, `GET` only (any other
method `405`, an unknown path `404`). It moved from 7734 to 7735 on
2026-09-11: sy-serendipity's dev server owns 7734 and its `kill-port` would
have killed the API. `localhost` can resolve to `[::1]`, where a stranger
may listen and look like a working, empty response. Always use the
literal IP.

## Endpoints

### `GET /health`

```bash
curl -s http://127.0.0.1:7735/health
```

`{ok, schema_version, schema_version_expected, db_path, db_mtime,
pollers: {loop, watchdog_poll, dispatch_sweep → {age_minutes, last_run,
threshold_minutes, ok}}, checked_at}`. `ok: false` means either the schema
assertion failed or a poller's heartbeat is older than 3× its own
LaunchAgent's interval — that is a finding, not a shrug: name which poller
and its age, don't just say "warden looks fine" because the endpoint answered.

### `GET /metrics`

```bash
curl -s http://127.0.0.1:7735/metrics
```

The six funnel numbers DESIGN.md defines as what "done" means for this
system: verdicts reaching a recorded disposition, the fixed-vs-silent ratio,
median time stuck in `needs_human`, unattended fixes per week, poller ages,
and reverts/reopens. Every leaf metric is `{"value": …, "unavailable": …}` —
**`value: null` paired with a non-empty `unavailable` reason means "not
measurable yet", never a measured zero.**

### `GET /board`

```bash
curl -s http://127.0.0.1:7735/board
```

`{generated_at, schema_version, counts: {<state>: n}, items: [{event_id,
origin, repo, state, state_deadline, max_tier, title, note, pr_url,
dispatch_job, implement_job, validation_job, created_at, updated_at}],
terminal_24h: n}` — every **non-terminal** item, newest first, plus how many
finished in the last 24h. "What is warden doing" is `counts` by state;
"what's blocked" is any item whose `state` is `needs_human` or
`merge_blocked`.

### `GET /items/<event_id>`

```bash
curl -s http://127.0.0.1:7735/items/<event_id>
```

`{item: {…every triage_items column…}, event: {source, external_id, title,
url, first_seen, resolved_at}, dispatches: [{job_id, tier, status,
created_at, finished_at, artifact_url, validation_status, verdict:
{summary, nextAction, confidence, recommendation}|null}], operations: […],
transitions: […]}`. `404` on an unknown id, `400` on a non-integer one. This
is the durable handle across an item's whole chain — investigate, implement
and validate can each be a different row in `dispatches`; only this endpoint
shows them together, which is why it's the answer to "what happened to
that", not `/board`'s one-line summary.

## How to answer

- **"What is warden doing"** → `/board`, read `counts`, name any state with
  items beyond `new`/`investigating`.
- **"What needs me"** → `/board`, filter to `needs_human` and
  `merge_blocked`, name each by `repo` + `note` — the `note` is why it's
  stuck; lead with it, not the state name.
- **"What happened to item N" / "is that PR merged yet"** → `/items/N`.
  Relay `item.state`, the latest `dispatches[].verdict.summary` if there is
  one, and `pr_url` if it exists.
- **"Is the loop healthy"** → `/health`. Say `ok`, and if it's `false`,
  which poller and how stale — "the loop hasn't run in 40 minutes" is the
  useful sentence, "no" on its own is not.

## Honesty rules

- **A `null` metric is unavailable, not zero.** Say "not measurable yet
  (`<unavailable reason>`)", never round it to "0".
- **A stale poller in `/health` is a finding — name it.** Don't just relay
  the top-level `ok` boolean.
- **Never write.** Nothing here opens, merges, aborts, or notes anything —
  that's `claude-dispatch`. Warden's write-adjacent endpoints
  (`POST /items/:id/intent`, `POST /items/:id/note`) live on a
  tailnet-only door meant for Argo, not this loopback surface.
- **Never guess an item's state.** If asked and you haven't called
  `/board` or `/items/:id` this turn, call it — a verdict the sweeper
  delivered earlier in the thread is a snapshot from when it was posted,
  not the item's current state.
- **`http://127.0.0.1:7735` only, never `localhost`.**
