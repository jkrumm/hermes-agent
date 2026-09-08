# Alert triage — the act-loop over watchdog.db

`scripts/triage.py` (`no_agent` cron, every 10 min via `scripts/triage-cron.py` —
**not yet registered**, see *Registering the cron* below) closes the loop
`scripts/watchdog-poll.py` opened but never acted on: deduplicated `events`
rows become one durable, updated-in-place Slack card per problem, with a real
sideclaw investigation attached once a signature repeats or stays open.
**No LLM call happens anywhere in this file.**

## Why this exists

Before this file, `#alerts` ran a full `reasoning_effort: high` LLM turn on
every inbound alert *message*, then post-hoc suppressed the reply with a
`NO_REPLY` marker for anything that wasn't new (`config.yaml`'s old
`channel_prompts.C0AS1LAUQ3C` block). Because `slack.reply_in_thread: true`
makes every alert its own session, that turn had zero memory of the last time
the exact same signature fired — the same `research-gateway job.reaped >= 1
(15m)` alert was triaged 61 times in one day, reaching the same conclusion
every time, without ever noticing a fix already existed. `watchdog-poll.py`
already deduplicates `#alerts` (and four other sources) into `events`
(`UNIQUE(source, external_id)`, grouped signatures via `normalize_title()`)
30 minutes at a time — nothing downstream ever consumed that dedup to *act*.
`events.dispatch_id` (a Phase 3 projection column) and `dispatches.origin_event_id`
existed for this purpose and were always NULL. This file is the missing act-loop
and the two edges it writes.

## Signals -> items -> episodes

| Layer | What | Table |
|-|-|-|
| Signal | One deduplicated alert row, owned by `watchdog-poll.py` | `events` |
| Item | One triage problem, 1:1 with an `events` row, owned by `triage.py` | `triage_items` |
| Episode | One sideclaw `investigate` dispatch, owned by `hermes-cc.sh` | `dispatches` |

`triage_items.event_id` is both the primary key and the stable identity across
a resolve -> recur cycle: a grouped or state source reuses the *same*
`events.id` when a signature reopens (`UNIQUE(source, external_id)`,
`resolved_at` reset to `NULL`), so a `triage_items` row's `artifact_url` and
`dispatch_job` from a PRIOR investigation survive a reopen — see
*Reopen preserves history* below, which is precisely the property that stops a
future re-triage from rediscovering a fix that already shipped.

Multiple items can share ONE episode: a **cluster** is every `triage_items`
row that shares a non-NULL `dispatch_job` value. There is no separate cluster
table or `cluster_id` column — membership is derived, and a cluster's
lifetime already equals its dispatch's lifetime. See *Escalation — the two
edges* and *Clustering* below.

## The loop, per run

1. **Ingest** — upsert one `triage_items` row per open event in
   `slack_alert`, `uk`, `docker_homelab`, `docker_vps`, `hermes_log`.
   `occurrences` comes from `payload_json.batch_count` (grouped sources) or
   falls back to `reminder_count + 1` (state sources, which don't batch).
   Never writes to `events.payload_json` — `upsert_grouped()` rewrites that
   blob wholesale on every poll (verified by reading it), so a second writer
   there would silently lose data. `triage_items` is a fully separate table
   for exactly this reason.
2. **Reopen / unsnooze** — a `triage_items` row stuck in `resolved` whose
   underlying event has since reopened flips back to `new` (never clearing
   `artifact_url`/`dispatch_job`); a `snoozed` row whose `snoozed_until` has
   passed flips back to `new`.
3. **Classify** — resolve `repo` by `fnmatch` against TWO match targets per
   event (`source:external_id` and `source:normalize_title(title)` — see
   *Match targets* below) using `config/triage-policy.json`'s `rules` (first
   match wins), or route to `ignored` via `ignore` (checked first, same two
   targets) or the structural `ignoreUnstructuredSlackProse` flag. Only ever
   touches a row still in state `new` — an escalated, snoozed, or manually
   ignored item is never reclassified out from under itself. A signature
   matching no rule stays `new` with `repo` unset and is named in the
   once-a-day unmapped-signatures digest (its own Slack message, not a
   per-item card) so the map can grow deliberately.
4. **Resolve** — an event whose `resolved_at` is now set flips its
   `triage_items` row to `resolved`.
5. **Dissolve** — a cluster whose folded verdict says its members don't
   share a root cause (`DISSOLVE_MARKER`, see *Clustering*) splits: every
   member resets to `new` and re-escalates independently later.
6. **Escalate** — every eligible `new`+mapped item, GROUPED BY REPO, becomes
   at most ONE sideclaw dispatch per repo per run (a cluster, capped at
   `MAX_CLUSTER_SIGNATURES` = 5 members; the rest wait for a later run) — not
   one dispatch per item. See *Clustering*.
7. **Card** — one Slack card per cluster (`_cluster_groups()`, keyed by
   `dispatch_job`), posted once state leaves `new` (see *Carded states*
   below) and updated in place after, no-op when the rendered content hasn't
   changed.
8. **Unmapped digest** — once per UTC day (tracked in the `cursors` table,
   shared with `watchdog-poll.py`), a single Slack message listing every
   signature that matched no rule this run.

`scripts/dispatch-sweep.py` closes the other half: when a dispatch tied to a
triage cluster (`dispatches.origin_event_id` set) reaches a terminal status,
it calls `triage.fold_dispatch_verdict()`, which now looks up EVERY
`triage_items` row sharing that `dispatch_job` (not just the primary member)
and folds the verdict onto all of them and their one shared card immediately,
rather than waiting up to 10 minutes for this file's own next pass. The
`#watchdog` delivery path for dispatches with no `origin_event_id` (every
non-triage dispatch) is unchanged.

## Match targets

A policy `rules`/`ignore` pattern is tried against TWO strings per event, in
order, first match across either wins:

1. `f"{source}:{external_id}"` — the raw form.
2. `f"{source}:{normalize_title(title)}"` — the human-readable form,
   `normalize_title()` imported from `scripts/watchdog-poll.py`.

For a grouped source (`slack_alert`, `hermes_log`) these are USUALLY the same
string — that source's `external_id` already IS `normalize_title(title)` (see
`aggregate_slack_batch()`/`poll_hermes_logs()`), so the second target is a
harmless no-op there. For a state source they differ, and this is what makes
`uk` mappable at all: its `external_id` is an opaque, unglobbable UptimeKuma
monitor id (`"204"`), unstable across a monitor recreate — a rule can only be
written against the title-derived target, e.g. `uk:macmini-dev-host-push`.

## Carded states

A card exists ONLY once a cluster has left `new` — state in `investigating`,
`verdict`, `needs_human`, `pr_open`, or `resolved`. An item that is mapped
but hasn't yet crossed `minOccurrences`/`minOpenMinutes` — or is simply
unmapped — is carried silently; it appears only in the once-a-day
unmapped-signatures digest (if unmapped) or not at all (if mapped but not yet
eligible). This is deliberate: an empty or partial policy must never turn
into dozens of cards of noise on day one, which is exactly what carding
every non-`ignored` row (regardless of state) used to do.

## State machine

```
new ──(escalate, clustered by repo)──> investigating ──(sweeper folds verdict)──┬──> verdict ──(DISSOLVE_MARKER)──> new (cluster splits)
 │                                                                                ├──> needs_human
 │                                                                                └──> pr_open
 ├──(ignore rule / ignoreUnstructuredSlackProse / --ignore)──> ignored  (terminal, never carded)
 ├──(--snooze)──> snoozed ──(snoozed_until passes)──> new
 └──(event resolves)──> resolved ──(event reopens)──> new
```

Any non-`ignored` state also goes to `resolved` the moment the underlying
event's `resolved_at` is set. Once resolved, the row's rendered content stops
changing, so the card-hash short-circuit (below) means it is genuinely never
touched again — "stop touching it" falls out of the state machine, it isn't a
separate rule.

## Clustering

Multiple signatures can share one root cause — the concrete example this was
built for: `research-gateway job.reaped` and `audio-gateway podcast.failed`
were both `threshold: 0` in the same commit, fixed by the same two-line diff
in `vps/observability/alerts/`. `escalate()` groups every eligible `new`+
mapped item BY RESOLVED REPO and opens AT MOST ONE sideclaw dispatch per repo
per run (capped at `MAX_CLUSTER_SIGNATURES` = 5 members; the overflow items
stay in `new` and wait for a later run — never dropped, never silently
folded in anyway).

Cluster membership is derived, never its own column: every CARDED-state
`triage_items` row sharing a non-NULL `dispatch_job` IS one cluster
(`_cluster_groups()`). A dedicated `cluster_id` column would just duplicate
that fact under a different name.

The grouping is a **hypothesis**, never an assertion — the brief tells the
episode so explicitly and asks it to confirm or split it: if the signatures
do NOT share a root cause, the episode is asked to say so using the exact
phrase `UNRELATED SIGNATURES` in its summary/verdict/recommendation. The very
next run's `maybe_dissolve_clusters()` does a plain, case-sensitive substring
check for that phrase on a `verdict`-state cluster (`needs_human`/`pr_open`
clusters found something actionable, so dissolving doesn't apply there) and,
on a match, resets every member to `new` via `_dissolve_cluster()` — which
posts one final "Cluster split" message on the shared card and clears its
`card_channel`/`card_ts`/`card_hash`, but DELIBERATELY LEAVES `dispatch_job`
set on the now-`new` rows, purely as a cooldown anchor (`_cooldown_ok()` still
finds the dissolved dispatch's `created_at`). Without that, the SAME run's
`escalate()` call would see both members freshly eligible with zero cooldown
and instantly re-fuse them into an identical cluster — dissolve would be a
no-op in practice. Accepted tradeoff: a dissolved pair could re-cluster again
after `cooldownHours` if both are still open; a hard permanent split would
need a negative-relationship table this schema doesn't have, and the split
verdict stays visible in `dispatches.verdict_json` regardless.

## Escalation — the two edges

`escalate_cluster()` shells out to:

```
scripts/hermes-cc.sh dispatch <repo> --tier investigate --json \
  --origin-event <primary member's events.id> --origin-channel <card channel>
```

with the brief on stdin (never argv — see `docs/dispatch-bridge.md`'s "brief
is data, never command" rule; capped in Python at `MAX_BRIEF_CHARS` = 8000
before it ever reaches the subprocess, matching hermes-cc.sh's own ceiling).
`--origin-event` takes exactly one `events.id` (one `dispatches` row = one
episode), so it's the cluster's PRIMARY member; `--origin-thread` is omitted
because the card doesn't exist yet at dispatch time (see *Carded states* —
`new` never has one). The card is posted immediately AFTER the dispatch
succeeds (the first time this cluster becomes `investigating`, a CARDED
state), and `escalate_cluster()` then does one small follow-up
`UPDATE dispatches SET origin_thread_ts=?` — the same "extra writer touching
one column it doesn't own" pattern `dispatch-sweep.py` already uses for
`status`/`verdict_json`/`artifact_url`/`merged_at`/`poll_misses`/
`reported_at` on this same table — so `dispatch-sweep.py`'s existing
actionable-dispatch nudge still lands on the card's own thread.

Two edges were always NULL before this file:

- `dispatches.origin_event_id` — hermes-cc.sh's `--origin-event` flag already
  existed and already writes this as part of its own `INSERT`; `escalate_cluster()`
  just has to pass the flag (for the primary member only — `--origin-event`
  takes a single id). No second writer races `dispatches` for this column.
- `events.dispatch_id` — nothing wrote this. `escalate_cluster()` looks up the
  freshly-inserted `dispatches.id` by `job_id` and does the
  `UPDATE events SET dispatch_id=?` for EVERY member of the cluster, not just
  the primary — this is the one edge nothing else can write, and it's what
  makes `watchdog-poll.py`'s existing `_dispatch_status()`/`_dispatch_summary()`
  projection work for every signature in the cluster, not only the first.

## The brief

Built from data actually available in this DB, never fabricated: per repo,
per member signature — occurrence count, first/last seen (absolute, UTC), up
to 3 distinct raw text snippets (`event.title` plus a grouped signature's
`payload_json.first_text`/`first_line` if distinct — **the schema does not
retain a full history of individual occurrences**, so this is a documented
best-effort rather than a fabricated 3-item history), and — the fix for the
61-re-triage scenario — that member's own `artifact_url` if a prior
investigation of this EXACT signature already produced one (see *Reopen
preserves history*) — plus up to 5 sibling open `triage_items` in the same
repo (excluding every cluster member). For a multi-member cluster, the brief
states explicitly that these signatures fired together and may share one
root cause, and asks the episode to confirm or split the hypothesis (see
*Clustering*).

## Cards

One Slack message per CLUSTER (not per item — see *Clustering*), in
`config/triage-policy.json`'s `cardChannel` (currently `C0BVDE5R562`,
`#agents` — shared with the agent-overview and project-narratives digests, a
deliberate reuse rather than a new channel), posted only once the cluster
reaches a carded state (see *Carded states*). First post -> `chat.postMessage`;
every subsequent change -> `chat.update` on the stored `card_ts`, never a
second `chat.postMessage` for the same cluster. Every member row carries an
identical copy of `card_channel`/`card_ts`/`card_hash` (rather than one
"owning" row), so cluster membership stays self-describing even after a
process restart. **The API call is skipped entirely when the rendered Block
Kit content's sha256 (`card_hash`) is unchanged since the last sync** — this
is the property that stops the channel becoming a firehose again, and it is
what makes "resolution updates the card once and then stops" fall directly
out of the state machine rather than needing special-case code.

Content: a header (state emoji + either the single member's title, or "N
related alerts in `repo`" for a multi-member cluster), a context line listing
EACH member's own signature and occurrence count, then state-dependent body —
the investigation job id while `investigating`; on `verdict`/`needs_human`/
`pr_open`, the summary + confidence + up to 3 evidence lines (all read live
from `dispatches.verdict_json` via `dispatch_job`, never duplicated into
`triage_items`) + the artifact URL as a link; `needs_human` additionally shows
the blocker (stored in `triage_items.note`, the one field this file uses for
free text). A footer context line always names the snooze command. **No
buttons in this change** — the interactive layer (Approve/Deny-style actions
on a card) is a deliberate follow-up, matching the note in the brief that
shipped this file.

## Reopen preserves history

A grouped or state source's `events` row is reused across a resolve -> recur
cycle (same `UNIQUE(source, external_id)` constraint `upsert_grouped()`/
`reconcile()` already rely on). `reopen_if_needed()` flips a `resolved`
`triage_items` row back to `new` without ever clearing `artifact_url` or
`dispatch_job`. The next time that signature escalates, `_build_brief()`
includes the prior artifact URL and tells the episode to check whether it
already fixes the problem — including whether it simply hasn't been merged
yet — before proposing something new. This is the direct fix for the
scenario in the brief that shipped this file: a PR already existed and 61
re-triages never noticed.

## `config/triage-policy.json` contract

```json
{
  "cardChannel": "C0BVDE5R562",
  "minOccurrences": 3,
  "minOpenMinutes": 30,
  "cooldownHours": 6,
  "ignoreUnstructuredSlackProse": true,
  "rules": [{"match": "<fnmatch on either match target>", "repo": "<repo name>"}],
  "ignore": ["<fnmatch on either match target>"]
}
```

A "signature" is `source:external_id` (`triage_items.signature`, and the
argument every `--snooze`/`--ignore`/`--reopen` CLI verb takes) — this is
distinct from a "match target", which is one of the two strings a `rules`/
`ignore` pattern is actually tried against (see *Match targets*). `rules` is
matched top-to-bottom, first match across either target wins; `ignore` is
checked first (both targets) and wins over `rules`.

`ignoreUnstructuredSlackProse` (bool) is checked before `ignore` for
`slack_alert` items specifically: any title that does not start with a
recognized bot-alert shape (`[`, the siren emoji, checkmark, warning, or a
bold-mrkdwn warning) is ignored outright. This exists because, before
`#alerts` was silenced, Hermes's OWN conversational replies in that channel
were ingested by `watchdog-poll.py`'s `slack_alert` poller right alongside
real bot alerts — hundreds of prose sentences sitting in `events` as if they
were alert signatures. Silencing the channel (`config.yaml`) stops new ones;
this flag is what keeps the existing backlog from getting carded on this
file's first run, without thirty hand-written prose globs that need updating
every time Hermes phrases a reply slightly differently.

Every `repo` MUST resolve under `root` in `config/dispatch-repos.json` and
MUST NOT be in that file's `deny` list — `triage.py` checks the deny list
itself before ever shelling out, so a bad rule degrades to "never escalates"
(logged to stderr) rather than a crash, but it is still a policy bug, not a
feature; fix the rule, don't rely on the guard. HyperDX-origin alerts
(`job.reaped`, `podcast.failed`, `vps-edge-*`, ...) map to `vps`, not to the
service they're ABOUT — their threshold/definition lives in
`vps/observability/alerts/*.json`, which is where the fix lands. Extend the
file with:

```bash
sqlite3 ~/.hermes/watchdog.db \
  "SELECT source, external_id, title FROM events WHERE resolved_at IS NULL ORDER BY first_seen DESC LIMIT 40;"
```

and a rule (or ignore pattern) for anything real that shows up unmapped —
remembering a `uk` rule almost always wants the title-derived target
(`uk:some-monitor-name-push`), never the bare numeric id — exactly what the
once-a-day unmapped-signatures digest is for.

The `_readme` key is a JSON-native comment block (JSON has no real comments);
it explains the same contract from inside the file itself.

## Bounds

| Constant | Default | Env override | Why |
|-|-|-|-|
| `MAX_OPEN_INVESTIGATIONS` | 3 | `TRIAGE_MAX_OPEN_INVESTIGATIONS` | Concurrency ceiling on open CLUSTERS (distinct `dispatch_job`s in `investigating`) — sideclaw's own concurrency is shared with every other dispatch source |
| `DAILY_INVESTIGATE_BUDGET` | 8 | `TRIAGE_DAILY_INVESTIGATE_BUDGET` | Well under hermes-cc.sh's own 20/day so a triage storm can never starve interactive dispatch. Counts clusters, not member items |
| `MAX_CLUSTER_SIGNATURES` | 5 | — | Signatures riding in one cluster's brief; the rest wait for a later run |
| `SUBPROCESS_TIMEOUT` | 60s | `TRIAGE_SUBPROCESS_TIMEOUT` | Bounds the hermes-cc.sh subprocess call inside a 10-minute cron |
| `MAX_BRIEF_CHARS` | 8000 | — | Mirrors hermes-cc.sh's own `MAX_BRIEF_CHARS`; enforced in Python before the brief reaches a subprocess |

`DAILY_INVESTIGATE_BUDGET` is counted from `dispatches.origin_event_id IS NOT
NULL AND created_at >= <today, UTC>` — the same marker `escalate_cluster()`
writes, so no separate accounting column is needed. Both caps are checked
once per run and decremented as clusters open, so a later repo in the same
run correctly sees an exhausted cap — including under `--dry-run`, where
`escalate_cluster()` always returns `None` (it never calls hermes-cc.sh), so
the caps still advance on the dry-run path specifically so a multi-repo
preview simulates what a real run would actually allow. A Slack or sideclaw
failure for one cluster logs to stderr and returns without aborting the rest
of the run — every DB write in the loop is per-cluster and independently
committed.

## CLI verbs

`--run` (default) · `--dry-run` · `--db <path>` · `--snooze <signature>
--hours N` · `--ignore <signature>` · `--reopen <signature>` · `--list`.
`--snooze`/`--ignore`/`--reopen` mutate `triage_items` and exit immediately —
they never call Slack or sideclaw. `--dry-run` runs the local bookkeeping
passes for real (ingest/reopen/unsnooze/classify/resolve — all side-effect-free
against `triage_items` alone) so a preview against a throwaway copy of
`watchdog.db` is meaningful, but never calls Slack (`post_blocks`/
`update_blocks`) and never shells out to `hermes-cc.sh` — those are the only
two externally-visible actions this file can take.

## Registering the cron

**Not done by this change — the user does it.** `scripts/triage-cron.py` is
the thin registered entry point (mirrors `agents-cron.py`/`narratives-cron.py`
exactly — `cron/lifecycle_guard.py` rejects a long registered script or one
whose comments quote command lines, so the logic lives in `triage.py` and the
loader stays terse):

```bash
hermes cron create "*/10 * * * *" --name "Alert triage" \
  --script triage-cron.py --no-agent --deliver slack:C0BVDE5R562
```

Verify with `hermes cron list` — `Script: triage-cron.py`, `Mode: no-agent
(script stdout delivered directly)`. Stdout is always empty in production
(triage.py posts/updates Slack cards directly and logs diagnostics to
stderr), so an idle 10-minute pass delivers nothing under `no_agent` — exactly
the same shape as `dispatch-sweep.py`'s own cron.

## Silencing `#alerts`

`config.yaml`'s `slack.require_mention_channels` now includes `C0AS1LAUQ3C`
(`#alerts`) alongside the two pre-existing echo channels — see that file's own
comment block for the full before/after. Mentioning Hermes directly in
`#alerts` still works for an ad-hoc question; only the reflexive per-message
LLM turn is gone.

## Tests

`tests/test_triage.py`, run with
`~/.hermes/hermes-agent/venv/bin/python3 tests/test_triage.py` (this repo's
`venv` has no pytest — see that file's own docstring; every `test_*` function
is still plain-`assert`, argument-free, so it is valid standalone pytest input
too, and the test file's `main()` runner would be redundant if pytest is ever
installed). 24 cases, covering: dedup (one card, one investigation across
repeated runs), an unescalated (`new`) item never getting a card — mapped or
not, the card-hash short-circuit, both edges (`events.dispatch_id`,
`dispatches.origin_event_id`), `minOccurrences`/`minOpenMinutes`/snooze/ignore/
`ignoreUnstructuredSlackProse` withholding, `uk` mapping via the title-derived
match target rather than its opaque external_id, the concurrency and daily
budget caps (including their simulation under `--dry-run` across multiple
repos in one pass), a denied and an unmapped repo never dispatching, two
eligible same-repo items clustering into exactly one dispatch/card with both
edges written on every member and both signatures in the brief, two eligible
different-repo items producing two independent dispatches, a cluster
dissolving back to individually-eligible `new` items on a
`UNRELATED SIGNATURES` verdict, the brief traveling on stdin capped at 8000
chars (the one test using a real subprocess stub rather than the in-process
fake dispatcher), resolution updating the card exactly once, `--dry-run`
touching neither Slack nor sideclaw, artifact-url survival across a reopen,
and `fold_dispatch_verdict()` updating every member of a cluster (not just
the primary).
