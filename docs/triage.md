# Alert triage — the act-loop over watchdog.db

`scripts/triage.py` (its own LaunchAgent, `com.jkrumm.hermes-triage`, every 10 min —
see *Why a LaunchAgent, not `hermes cron`* below) closes the loop
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
   `slack_alert`, `uk`, `docker_homelab`, `docker_vps`, `hermes_log`,
   `op_refs_homelab`, `op_refs_vps`. `occurrences` comes from
   `payload_json.batch_count` (grouped sources) or falls back to
   `reminder_count + 1` (state sources, which don't batch). Never writes to
   `events.payload_json` — `upsert_grouped()` rewrites that blob wholesale on
   every poll (verified by reading it), so a second writer there would
   silently lose data. `triage_items` is a fully separate table for exactly
   this reason.
2. **Reopen / unsnooze** — a `triage_items` row stuck in `resolved` whose
   underlying event has since reopened flips back to `new` (never clearing
   `artifact_url`/`dispatch_job`); a `snoozed` row whose `snoozed_until` has
   passed flips back to `new`.
3. **Classify** — fnmatch TWO match targets per event (`source:external_id`
   and `source:normalize_title(title)` — see *Match targets* below) against
   `config/triage-policy.json`, in this order:
   1. `ignore` (checked first, both targets) — a deliberate human call that
      THIS signature is a genuine recovery or known-benign pattern. Routes
      to `ignored`: terminal, invisible, never in the digest.
   2. `ignoreUnstructuredSlackProse` (structural, `slack_alert` only) — a
      title that doesn't start with a recognized bot-alert shape. Routes to
      `STATE_NOTE`: terminal, but VISIBLE in the daily digest — see *Notes vs
      ignored* below.
   3. `rules` (first match wins) — resolves EITHER `repo` (escalate to a
      sideclaw episode) OR `verb` (run a declared local command — see *Verb
      outcomes*).
   Only ever touches a row still in state `new` — an escalated, snoozed, or
   manually ignored/noted item is never reclassified out from under itself.
   A signature matching no rule stays `new` with `repo`/`verb` unset and is
   named in the daily digest so the map can grow deliberately.
4. **Resolve** — an event whose `resolved_at` is now set flips its
   `triage_items` row to `resolved` — except `ignored`/`snoozed`/`STATE_NOTE`
   rows, which stay in their terminal state (a note must never get a
   one-time "resolved" card either). `note` is also cleared here, so a stale
   quiet/recovery note (below) never survives into a later, unrelated
   resolve.
4b. **Quiet / recovery-paired resolve** — the two GROUPED sources
   (`slack_alert`, `hermes_log`) never disappearance-resolve via step 4 at
   all: `watchdog-poll.py`'s own `sweep_stale_grouped()` only clears them
   after 7 idle DAYS, deliberate housekeeping, not signal. Two triage-side
   fixes instead, checked in this order and never touching
   `events.resolved_at`: `resolve_recovery_paired()` looks for a fresh `✅`
   HyperDX recovery message pairing the same alert text, and
   `resolve_quiet_grouped()` falls back to a `quietResolveHours` silence
   timer. See *Evidence commands and grouped-source resolution* below.
5. **Dissolve** — a cluster whose folded verdict says its members don't
   share a root cause (`DISSOLVE_MARKER`, see *Clustering*) splits: every
   member resets to `new` and re-escalates independently later.
6. **Escalate** — every eligible `new`+`repo`-mapped item, GROUPED BY REPO,
   becomes at most ONE sideclaw dispatch per repo per run (a cluster, capped
   at `MAX_CLUSTER_SIGNATURES` = 5 members; the rest wait for a later run) —
   not one dispatch per item. See *Clustering*.
6b. **Verbs** — every eligible `new`+`verb`-mapped item runs its allowlisted
   local command once. See *Verb outcomes*.
7. **Card** — one Slack card per cluster (`_cluster_groups()`, keyed by
   `dispatch_job`, a verb outcome is its own singleton "cluster"), posted
   once state leaves `new` (see *Carded states* below) and updated in place
   after, no-op when the rendered content hasn't changed.
8. **Daily digest** — once per UTC day (tracked in the `cursors` table,
   shared with `watchdog-poll.py`), a single Slack message with up to two
   sections: signatures that matched no rule, and `STATE_NOTE` rows.

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

## Notes vs ignored

Two different terminal, uncarded outcomes for a `slack_alert` item that
never becomes an episode — deliberately NOT the same state:

- **`ignored`** — the explicit `ignore` list. A human decided THIS
  signature is a genuine recovery or known-benign pattern. Invisible:
  never carded, never in the digest.
- **`STATE_NOTE`** — the structural `ignoreUnstructuredSlackProse` fallback.
  A title that doesn't start with a recognized bot-alert shape (`[`, siren,
  checkmark, warning). Visible: named (signature + a truncated title) under
  its own heading in the daily digest, though never carded or escalated.

The split exists because `watchdog.db` genuinely contains rows like a human
Slack message diagnosing the exact 1Password rate-limit root cause with a
concrete two-line fix — never shipped. Before `#alerts` was silenced, Hermes
replied to every message in that channel, and `watchdog-poll.py`'s
`slack_alert` poller ingested those replies right alongside real bot alerts;
routing all of that unstructured backlog into `ignored` would make a real,
unactioned diagnosis permanently invisible — precisely the failure mode this
whole redesign exists to kill. Routing it to `ignored` was the original
(wrong) design of `ignoreUnstructuredSlackProse`; `STATE_NOTE` fixed it.

## Verb outcomes

A policy rule can carry `verb` instead of `repo` — routes to a declared,
CODE-SIDE ALLOWLISTED local command (`VERB_ALLOWLIST` in `scripts/triage.py`)
rather than a sideclaw episode. The policy file names a KEY (`"env-check"`),
never a command — a policy file must never be able to name an arbitrary
argv, the same closed-verb-set principle `hermes-cc.sh`'s own
dispatch/status/list/merge/cancel verbs use, applied to a bounded local
probe instead of an episode.

Seeded with exactly one: `env-check` (`hermes-ops.sh env-check --json`, two
sequential ssh probes of homelab/vps's shared `.env.tpl`), which
`op_refs_homelab`/`op_refs_vps` route to. A dead 1Password ref blocks every
future reseal of the mini's offline secrets cache (`dotfiles/CLAUDE.md`
§Secrets) — it is a deterministic, already-diagnosed condition the moment
`env-check` runs, so dispatching a sideclaw episode to "investigate" it would
be both slower and actively worse: a bare 1Password item name in a
DISPATCHED verdict can collide with sideclaw's own `op://vault/item/field`
secret-scan pattern and get withheld from the card, whereas `env-check`'s
output reaching the card directly does not have that problem.

`run_verbs()` applies the same `minOccurrences`/`minOpenMinutes` eligibility
gate as an episode escalation, but NO concurrency/daily-budget cap (a verb is
a bounded local probe, not a sideclaw episode, and doesn't compete for that
budget) and NO cooldown tracking — a verb-routed item runs AT MOST ONCE,
because its terminal state (`needs_human`) permanently falls out of the
`state=new` candidate query. If the underlying condition later clears, the
normal resolve path (`events.resolved_at`) closes the row out without
needing a re-run; if it recurs after a reopen, running the probe again is
exactly correct. `VERB_TIMEOUT` = 260s (comfortably over `env-check`'s two
sequential 120s-bounded ssh probes) — long for a 10-minute cron, but the
probe runs at most once per dangling-ref episode, not every cycle.

The card's `note` (rendered by `_render_env_check_note()`) IS the whole
verdict: every dangling item name plus the exact remediation
(`make secrets-seed`, biometric, MacBook only) inlined, so no further
investigation should be needed.

**A prerequisite fix in `watchdog-poll.py` makes this trustworthy at all.**
`poll_op_refs()`'s `raw:` fallback (when `op run`'s error can't be parsed
into a specific dangling item name) used to build its dedup key from the
raw stderr text UNCHANGED — and that text embeds a timestamp (`[ERROR]
2026/09/01 15:00:34 (504) Unknown: ...`). Because `normalize_title()` does
not strip timestamps, every 30-minute poll minted a brand-new `external_id`,
so `reconcile()`'s disappearance logic resolved the "old" row and inserted a
"new" one every cycle — the DB reported the dangling ref clearing every 30
minutes while it stayed dead indefinitely, and this loop would have kept
escalating an ever-fresh signature into `run_verbs()` instead of running the
probe once and landing on a stable `needs_human` row. `_strip_op_refs_timestamps()`
strips ISO-8601 and slash/dash-separated date-time shapes plus any bare
6+-digit run from the text BEFORE it reaches `normalize_title()` — on this
one fallback path only; `normalize_title()` itself is unchanged, every other
source depends on its current behavior.

## Evidence commands

Every real investigation this loop has run so far (meteo, vps, hermes-agent)
came back `nextAction: human` citing the SAME reason: the dispatched sideclaw
episode runs in a read-only repo WORKTREE, which has the repo but never the
live machine — `var/health.json` and `watchdog-alerts.log` are gitignored/
empty there, live OTel data isn't in the checkout at all, and the one episode
that got anywhere only did because `~/.hermes/gateway-starts.log` happens to
sit outside the worktree by accident. A policy `rules` entry can now carry an
optional `evidence` list, fencing DECLARED, read-only, bounded probes into the
escalation brief — same closed-set principle as `verb` (see *Verb outcomes*):
this file names KEYS from `EVIDENCE_ALLOWLIST` in `scripts/triage.py`, never a
command or argv. An unknown key drops the WHOLE rule at `load_policy()` time,
loudly, exactly like an unknown `verb`.

Seeded with four:

| Key | What | Why it can't come from the repo checkout |
|-|-|-|
| `meteo-health` | meteo's own `var/health.json`, summarized (ok/heartbeat/timestamp + failing checks only, never dumped raw) | gitignored, empty in the worktree |
| `gateway-starts` | The last 5 lines of `~/.hermes/gateway-starts.log` (an append-only ledger of every gateway process start) | Outside every repo worktree by construction |
| `hermes-log-tail` | The tail of Hermes's `errors.log`, SLICED at the current gateway process start | Same file, same boundary requirement as `skills/hermes-gateway/SKILL.md` Rule 0 — an unsliced tail mixes a dead incarnation's errors with the live one |
| `kuma-push-last` | The live `[<monitor name>] ...` UptimeKuma push text for a `uk`-sourced cluster member | `events.payload_json` for a `uk` row is literally `{"type", "status"}` (see `poll_uk()`) — the actual heartbeat line (e.g. `FAIL: disk 90% used`) exists ONLY in raw #alerts Slack text, which `poll_slack_messages()`'s `skip_uk_push` deliberately drops before it ever reaches `events`; argo's own monitor endpoint doesn't carry it either |

Three of the four run as bounded, in-process Python (local file reads); the
fourth (`kuma-push-last`) additionally needs a secret (`HOMELAB_API_KEY`,
which must never cross an argv/`ps` boundary) and per-cluster context (which
monitor actually fired) that a fixed subprocess argv has no way to carry — see
`EVIDENCE_ALLOWLIST`'s own comment for why this deliberately diverges from
`VERB_ALLOWLIST`'s literal-argv shape while keeping the identical closed-key
contract. Every gatherer runs under `_run_bounded()` (a hard wall-clock
timeout, `TRIAGE_EVIDENCE_TIMEOUT`, default 20s) and any exception folds into
a returned error string — a failing evidence command is non-fatal and never
aborts the run; the brief still gets built with whatever evidence succeeded.

Evidence is rendered into one clearly-labelled block inside the brief,
explicitly told to the episode as CAPTURED runtime state gathered by the loop
— authoritative for what it reports, but not re-runnable by the episode
itself and possibly already stale by the time it's read. It is capped twice:
each key at `EVIDENCE_CAP_CHARS` (1200), the whole block at
`EVIDENCE_TOTAL_CAP_CHARS` (3200) or whatever budget the REST of the brief
(the alert list, sibling items, closing instructions) leaves behind inside
`MAX_BRIEF_CHARS` — whichever is smaller. When evidence has to be cut, only
evidence is cut, never the brief's own structure, and the block says so
("…truncated to fit the brief cap"). `config/triage-policy.json` seeds
`meteo-health` on the meteo rules, `kuma-push-last` on every `uk:*` rule, and
`gateway-starts`/`hermes-log-tail` on the hermes-agent-related `uk:hermes-*`
and `hermes_log:*` rules.

## Grouped-source resolution (quiet timer + recovery pairing)

`slack_alert` and `hermes_log` (`GROUPED_TRIAGE_SOURCES`) are the two
INGEST_SOURCES that are grouped (`upsert_grouped()`-based, append-only) rather
than state (`reconcile()`-based, disappearance-resolved) — the concrete gap
this closes: `research-gateway job.reaped`/`audio-gateway podcast.failed`
were fixed and deployed to prod HyperDX at ~18:37, the alert itself posted
`✅ resolved` at 18:45, and the `triage_items` row stayed open regardless,
because step 4 above only ever fires from `events.resolved_at`, and
`watchdog-poll.py`'s own `sweep_stale_grouped()` — which this file
deliberately never touches; that column and that sweep stay owned end to end
by `watchdog-poll.py` — only clears a grouped row after 7 idle DAYS.

Two triage-SIDE fixes (`triage_items` state only, never `events.resolved_at`),
checked in this order, both excluding an item mid-investigation
(`state == investigating` — an open dispatch should finish before either path
races it):

- **`resolve_recovery_paired()`** — a `✅ <same alert text>` HyperDX recovery
  message is a strictly better signal than silence: a service that is fully
  DOWN also stops emitting, so absence of new occurrences alone can never
  tell the two apart. This is cheap because HyperDX's webhook posts the
  IDENTICAL alert text with only the leading glyph flipped, and
  `normalize_title()` already strips every non-alnum character — including
  both glyphs — so `✅ research-gateway job.reaped >= 1 (15m)` and
  `🚨 research-gateway job.reaped >= 1 (15m)` normalize to the exact same
  string, which for a grouped source already IS the event's own stable
  `external_id` (see *Match targets*). One fresh #alerts fetch per run (not
  per item), one dict lookup per open `slack_alert` candidate. This CANNOT be
  read back out of `events`/`payload_json` — `upsert_grouped()` retains only
  one title per batch, never a per-occurrence history (see *The brief*) — so
  reading live #alerts is the only way to see it at all. Skipped entirely
  under `--dry-run`, same as every other outbound call this file makes.
- **`resolve_quiet_grouped()`** — the fallback: a row whose underlying event
  has produced no new occurrence in `quietResolveHours` (policy knob, default
  2h — comfortably past the 30-min watchdog-poll cadence and short of either
  source's own 6h/24h reminder window, so one missed poll can never trip a
  false resolve) flips to `resolved`. No new column needed:
  `last_reminder_at`/`notified_at`/`first_seen` (the same idle anchor
  `sweep_stale_grouped()` itself uses) only advances when `watchdog-poll.py`
  re-stamps the row on a fresh occurrence, so a value that has stopped
  changing already IS the quiet duration. Pure local bookkeeping (no Slack,
  no dispatch), so it runs for real even under `--dry-run`, like
  `apply_resolutions()`.

**Neither path ever means "fixed."** A service that is fully down also stops
emitting, so silence is never proof of anything beyond silence, and a ✅
message is HyperDX's own claim, not this loop's. The resolved card always
reads "signal quiet since \<time\>" (`QUIET_RESOLVE_NOTE_PREFIX`) or "recovery
message observed: …" (`RECOVERY_PAIRED_NOTE_PREFIX`) — `render_card_blocks()`
only surfaces `note` on a `resolved` card when it starts with one of those two
prefixes, specifically so an ordinary event-driven resolve (which clears
`note` outright) never inherits stale text from an earlier phase.

## Carded states

A card exists ONLY once a cluster has left `new` — state in `investigating`,
`verdict`, `needs_human`, `pr_open`, or `resolved`. An item that is mapped
but hasn't yet crossed `minOccurrences`/`minOpenMinutes` — or is simply
unmapped — is carried silently; it appears only in the daily digest (if
unmapped) or not at all (if mapped but not yet eligible). `ignored` and
`STATE_NOTE` are excluded too — see *Notes vs ignored*. This is deliberate:
an empty or partial policy must never turn into dozens of cards of noise on
day one, which is exactly what carding every non-`ignored` row (regardless of
state) used to do.

## State machine

```
new ──(escalate, clustered by repo)──> investigating ──(sweeper folds verdict)──┬──> verdict ──(DISSOLVE_MARKER)──> new (cluster splits)
 │                                                                                ├──> needs_human
 │                                                                                └──> pr_open
 ├──(verb outcome — run_verbs())──> needs_human  (terminal-ish: no dispatch_job, runs at most once)
 ├──(ignore rule / --ignore)──> ignored  (terminal, never carded, never digested)
 ├──(ignoreUnstructuredSlackProse)──> note  (terminal, never carded, but IN the daily digest)
 ├──(--snooze)──> snoozed ──(snoozed_until passes)──> new
 └──(event resolves)──> resolved ──(event reopens)──> new
```

Any state EXCEPT `ignored`/`snoozed`/`note` also goes to `resolved` the
moment the underlying event's `resolved_at` is set. Once resolved, the row's
rendered content stops changing, so the card-hash short-circuit (below)
means it is genuinely never touched again — "stop touching it" falls out of
the state machine, it isn't a separate rule.

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
  "quietResolveHours": 2,
  "ignoreUnstructuredSlackProse": true,
  "rules": [
    {"match": "<fnmatch on either match target>", "repo": "<repo name>",
     "evidence": ["<EVIDENCE_ALLOWLIST key>", "..."]},
    {"match": "<fnmatch on either match target>", "verb": "<VERB_ALLOWLIST key>"}
  ],
  "ignore": ["<fnmatch on either match target>"]
}
```

`evidence` is optional and only ever valid alongside `repo` (never `verb` — a
verb outcome is already a deterministic local probe, not an episode with a
brief to fence evidence into). `quietResolveHours` is top-level, not
per-rule — see *Grouped-source resolution* above.

A "signature" is `source:external_id` (`triage_items.signature`, and the
argument every `--snooze`/`--ignore`/`--reopen` CLI verb takes) — this is
distinct from a "match target", which is one of the two strings a `rules`/
`ignore` pattern is actually tried against (see *Match targets*). A rule
carries EITHER `repo` (escalate to a sideclaw episode) OR `verb` (run a
declared local command — see *Verb outcomes*), never both; `rules` is
matched top-to-bottom, first match across either target wins.

Evaluation order (see *The loop, per run* step 3, *Notes vs ignored*):
`ignore` first (checked both targets, wins over everything — genuine
recoveries/known-benign), then `ignoreUnstructuredSlackProse` (structural,
`slack_alert` only, routes to `STATE_NOTE` not `ignored`), then `rules`.

Every `repo` MUST resolve under `root` in `config/dispatch-repos.json` and
MUST NOT be in that file's `deny` list — `triage.py` checks the deny list
itself before ever shelling out, so a bad rule degrades to "never escalates"
(logged to stderr) rather than a crash, but it is still a policy bug, not a
feature; fix the rule, don't rely on the guard. Every `verb` MUST be a key in
`scripts/triage.py`'s `VERB_ALLOWLIST` — `load_policy()` drops (with a
stderr warning) any rule naming an unknown verb, rather than silently never
matching it at classify() time.

**Which repo owns an infra-signal alert** (a real VPS outage trace caught
this policy wrong once already — the argo rules used to point at `argo`):
an infra-signal alert about a RollHook-managed app maps to the repo that owns
its COMPOSE FILE AND DEPLOY TARGET, not the repo that owns its source.
`argo` is compose-managed manually inside `vps` (`apps/argo/compose.yml`,
`make argo-up` — nothing in argo's own repo redeploys it), so a downed argo
container — and its `api-*`/`dashboard-*` UptimeKuma child monitors — maps
to `vps`. Most OTHER vps-hosted apps in this policy (audio-gateway,
research-gateway, meteo, image-gen, image-share) are the opposite:
`dispatch-repos.json`'s own comment documents that they deploy to the VPS on
every push to THEIR OWN repo's master (GitHub Actions -> RollHook), so a code
fix in their own repo auto-redeploys — mapping those to their own repo is
correct and deliberate. Before adding a new vps-app rule, check
`vps/apps/<name>/compose.yml` AND whether that app's own repo has a deploy
workflow. HyperDX-origin alerts (`job.reaped`, `podcast.failed`,
`vps-edge-*`, ...) map to `vps` for a related but distinct reason: their
threshold/definition lives in `vps/observability/alerts/*.json`, which is
where THAT fix lands regardless of which service the alert is about.

Extend the file with:

```bash
sqlite3 ~/.hermes/watchdog.db \
  "SELECT source, external_id, title FROM events WHERE resolved_at IS NULL ORDER BY first_seen DESC LIMIT 40;"
```

and a rule (or ignore pattern) for anything real that shows up unmapped —
remembering a `uk` rule almost always wants the title-derived target
(`uk:some-monitor-name-push`), never the bare numeric id — exactly what the
daily digest is for.

The `_readme` key is a JSON-native comment block (JSON has no real comments);
it explains the same contract from inside the file itself.

## Bounds

| Constant | Default | Env override | Why |
|-|-|-|-|
| `MAX_OPEN_INVESTIGATIONS` | 3 | `TRIAGE_MAX_OPEN_INVESTIGATIONS` | Concurrency ceiling on open CLUSTERS (distinct `dispatch_job`s in `investigating`) — sideclaw's own concurrency is shared with every other dispatch source |
| `DAILY_INVESTIGATE_BUDGET` | 8 | `TRIAGE_DAILY_INVESTIGATE_BUDGET` | Well under hermes-cc.sh's own 20/day so a triage storm can never starve interactive dispatch. Counts clusters, not member items |
| `MAX_CLUSTER_SIGNATURES` | 5 | — | Signatures riding in one cluster's brief; the rest wait for a later run |
| `SUBPROCESS_TIMEOUT` | 60s | `TRIAGE_SUBPROCESS_TIMEOUT` | Bounds the hermes-cc.sh subprocess call inside a 10-minute cron |
| `VERB_TIMEOUT` | 260s | — | `env-check` runs TWO sequential ssh probes, each individually bounded by hermes-ops.sh's own `SSH_TIMEOUT=120` — the outer bound has to clear 240s or it would kill a legitimately slow-but-healthy probe |
| `MAX_BRIEF_CHARS` | 8000 | — | Mirrors hermes-cc.sh's own `MAX_BRIEF_CHARS`; enforced in Python before the brief reaches a subprocess |
| `EVIDENCE_TIMEOUT` | 20s | `TRIAGE_EVIDENCE_TIMEOUT` | Hard wall-clock bound per evidence gatherer (a stuck file read or a slow argo API call must never stall a 10-minute cron) |
| `EVIDENCE_CAP_CHARS` | 1200 | — | Per-key cap on rendered evidence text, before the whole-block cap below |
| `EVIDENCE_TOTAL_CAP_CHARS` | 3200 | — | Whole evidence block cap — well under `MAX_BRIEF_CHARS` so a 5-signature cluster (each pulling its own evidence) still leaves room for the rest of the brief |
| `DEFAULT_QUIET_RESOLVE_HOURS` | 2h | policy `quietResolveHours` | Grouped-source (`slack_alert`/`hermes_log`) quiet-timer resolve — see *Grouped-source resolution* |

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

## Why a LaunchAgent, not `hermes cron`

**This file originally proposed registering `triage.py` as a `hermes cron`
`no_agent` job** (via a thin `triage-cron.py` loader, the same shape as
`agents-cron.py`/`narratives-cron.py`/`dispatch-sweep-cron.py`). An adversarial
review found the structural flaw before that registration ever happened: a
`hermes cron` job is scheduled and run *inside* the `ai.hermes.gateway`
process, so the loop whose entire job is noticing Hermes is broken cannot run
when Hermes is down. Four real, currently-open `hermes_log` rows in
`watchdog.db` are exactly that class — one (`slack_bolt.AsyncApp: Failed to
connect`) open 11 days with `reminder_count` 5 and no action ever taken,
because the only delivery path a gateway-scheduled job has is the same Slack
connection that row says is broken.

`triage.py` is instead installed by `make setup` as its own LaunchAgent
(`com.jkrumm.hermes-triage`, `launchd/com.jkrumm.hermes-triage.plist.template`,
`StartInterval 600`) invoking `~/.hermes/hermes-agent/venv/bin/python3
scripts/triage.py --run` directly — no gateway process in the loop at all.
This is safe specifically because Slack delivery here was already independent
of the gateway: `post_blocks`/`update_blocks` call `chat.postMessage`/
`chat.update` over plain HTTP with a token from `resolve_slack_token()`
(`secrets-run read op://hermes/slack/bot-token`, same as `agents-overview.py`),
never the gateway's live `slack_bolt.AsyncApp` connection — so this keeps
working with the gateway fully stopped, which is the one case it exists for.

`scripts/triage-cron.py`, the thin `hermes cron`-registered loader this
section used to describe, is deleted — a `hermes cron` registration is now
the wrong home for this loop, and a dead loader that still works correctly is
a trap for the next reader (it would silently duplicate every card/dispatch if
ever registered by hand). `dispatch-sweep.py`'s own cron loader
(`dispatch-sweep-cron.py`) is unrelated and unaffected: that job only *reads*
sideclaw and folds a verdict onto a card `triage.py` already wrote, so it has
no chicken-and-egg dependency on the gateway being up.

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
installed). 30 cases, covering: dedup (one card, one investigation across
repeated runs), an unescalated (`new`) item never getting a card — mapped or
not, the card-hash short-circuit, both edges (`events.dispatch_id`,
`dispatches.origin_event_id`), `minOccurrences`/`minOpenMinutes`/snooze/ignore/
`ignoreUnstructuredSlackProse` withholding, unstructured prose landing in
`STATE_NOTE` (not `ignored`), producing zero cards, and appearing in the
digest payload, `uk` mapping via the title-derived match target rather than
its opaque external_id, `op_refs_homelab`/`op_refs_vps` being ingested and
routed to the `env-check` verb rather than an episode (both the dangling-item
and the nothing-dangling shapes), an unknown verb key being rejected at
`load_policy()` time, the shipped `config/triage-policy.json`'s `api-*`/
`dashboard-*`/argo rules resolving to `vps` (not `argo`, not the service's
own repo), the concurrency and daily budget caps (including their simulation
under `--dry-run` across multiple repos in one pass), a denied and an
unmapped repo never dispatching, two eligible same-repo items clustering into
exactly one dispatch/card with both edges written on every member and both
signatures in the brief, two eligible different-repo items producing two
independent dispatches, a cluster dissolving back to individually-eligible
`new` items on a `UNRELATED SIGNATURES` verdict, the brief traveling on
stdin capped at 8000 chars (the one test using a real subprocess stub rather
than the in-process fake dispatcher), resolution updating the card exactly
once, `--dry-run` touching neither Slack nor sideclaw, artifact-url survival
across a reopen, `fold_dispatch_verdict()` updating every member of a cluster
(not just the primary), and — directly against `scripts/watchdog-poll.py`,
not through triage.py — two `raw:` op-refs stderr strings differing only in
their timestamp producing the identical dedup key.

42 cases total — the later 12 cover *Evidence commands* and *Grouped-source
resolution*: each of the four evidence keys producing correctly-shaped,
bounded output (`meteo-health` summarizing rather than dumping, `gateway-
starts` showing only the 5 most recent, `hermes-log-tail` excluding every
line before its computed gateway-start boundary, `kuma-push-last` picking the
chronologically latest bracket match and normalizing away the glyph), a
raising gatherer folding into an error string without taking down a sibling
key's evidence or the run, an unknown evidence key dropping the whole rule at
`load_policy()`, a brief whose evidence had to be cut still landing under
`MAX_BRIEF_CHARS` with its closing structure intact and a truncation note
present, a grouped item resolving after `quietResolveHours` and updating its
card exactly once, an in-flight `investigating` item never being yanked to
resolved by the quiet timer, the `✅`-recovery-pairing path resolving on the
very next run without waiting out the timer, and `--dry-run` making zero
Slack calls for the pairing check.
