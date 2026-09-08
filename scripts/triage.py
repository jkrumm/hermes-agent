"""Alert triage — the act-loop that turns deduplicated watchdog.db events into
one durable, updated-in-place Slack card per problem, with a real sideclaw
investigation attached once a signature repeats or stays open. THE ACT PATH
(ingest -> classify -> cluster -> escalate -> card -> resolve) MAKES NO LLM
CALL AT ALL (the dispatched sideclaw `investigate` episode itself runs Claude
Code, which is inherent to what "investigate" means — that is a property of
hermes-cc.sh, not of this script). The ONE exception in the whole file is
`propose_mappings()` — a bounded, once-a-day maintenance pass, batched, never
in the act path itself — see PROPOSE MAPPINGS below.

Runs every 10 min as a Hermes `no_agent` cron script (via triage-cron.py, the
thin loader — see that file's docstring for why it has to stay thin).

WHY THIS EXISTS. `scripts/watchdog-poll.py` already ingests `#alerts` and the
other sources into `events` (deduplicated by `normalize_title()`/UNIQUE(source,
external_id)), but nothing ever ACTED on that dedup — Hermes instead ran a full
`reasoning_effort: high` LLM turn on every inbound alert MESSAGE, discarding
most of the replies via a NO_REPLY marker. Because `slack.reply_in_thread: true`
makes every alert its own session, that turn had zero memory of the last time
the exact same signature fired: the same `research-gateway job.reaped >= 1
(15m)` alert was triaged 61 times in one day, reaching the same conclusion each
time, without ever noticing a fix already existed. See config.yaml's `slack:`
comment block and docs/triage.md for the full before/after.

THE LOOP, once per run — see docs/triage.md for the full state machine:
  1. Ingest      — upsert one triage_items row per open ingest-source event,
                   including op_refs_homelab/op_refs_vps (a dead 1Password
                   ref blocks every future secrets-cache reseal — this must
                   reach at least the digest, never silently drop).
  2. Reopen/unsnooze — undo a stale `resolved`/`snoozed` state the underlying
                   event has since moved past (grouped sources reuse the same
                   events.id across a resolve -> recur cycle, so this is a
                   state fix-up, never a new row).
  3. Classify     — fnmatch MULTIPLE targets per event (see MATCH TARGETS
                   below) against config/triage-policy.json, in order: the
                   explicit `ignore` list (genuine recoveries/known-benign —
                   route to `ignored`, terminal, invisible), the structural
                   `ignoreUnstructuredSlackProse` fallback (route to
                   STATE_NOTE — terminal, but VISIBLE in the digest, see that
                   state's own docstring for why), then `rules` (resolve
                   EITHER `repo`, escalate to an episode, OR `verb`, run a
                   declared local command — see VERB OUTCOMES below). Only
                   ever touches a row still in state `new`.
  4. Resolve      — an event whose events.resolved_at is now set flips its
                   triage_items row to `resolved`.
  4b. Quiet/paired resolve — the two GROUPED_TRIAGE_SOURCES (slack_alert,
                   hermes_log) never disappearance-resolve via step 4 at all
                   (watchdog-poll.py's own sweep_stale_grouped only clears
                   them after 7 idle days). resolve_recovery_paired() checks
                   a fresh #alerts fetch for a `✅`-prefixed message pairing
                   the same alert text (see that function's own docstring);
                   resolve_quiet_grouped() falls back to a quietResolveHours
                   silence timer. Neither ever claims "fixed" — see
                   QUIET_RESOLVE_NOTE_PREFIX/RECOVERY_PAIRED_NOTE_PREFIX.
  5. Dissolve     — a cluster (see CLUSTERING below) whose folded verdict says
                   its members do not share a root cause splits back into
                   individually-eligible `new` items.
  6. Escalate     — every `new`+`repo`-mapped+eligible item, GROUPED BY REPO,
                   becomes at most one sideclaw `investigate` dispatch per
                   repo per run (a cluster), not one per item.
  6b. Verbs       — every `new`+`verb`-mapped+eligible item runs its
                   allowlisted local command once (see VERB OUTCOMES) — never
                   an episode, never clustered with repo-mapped items.
  7. Card         — one Slack card per cluster (or per verb outcome), posted
                   once state leaves `new` (an unescalated item, mapped or
                   not, is carried silently — see CARDED STATES below) and
                   updated in place after, no-op when the rendered content
                   hasn't changed.
  8. Propose      — at most once per 24h (see PROPOSE MAPPINGS below), one
                   batched LLM call over signatures that have stayed `new`
                   with no `repo`/`verb` for longer than
                   `proposeMappingsAgeDays`, proposing `map`/`ignore`/`unsure`
                   per signature. Applied outcomes land ONLY in
                   config/triage-policy.json (never triage_items directly),
                   committed (never pushed) in this repo's own checkout.
  9. Once a day, one digest message with up to three sections: signatures
     that matched no policy rule, STATE_NOTE rows (see step 3), and whatever
     step 8 just auto-added this run.

PROPOSE MAPPINGS — the one LLM call in this file. `config/triage-policy.json`
was designed to grow only by a human reading the daily unmapped digest and
hand-editing the file — measurably not happening: a signature that fired, got
hand-fixed once, then reappeared four months later matched nothing, because
the fix was never turned into a rule. `propose_mappings()` closes that loop
as cheaply as this problem allows: at most once per 24h (a cursor in
`cursors`, the same table the digest already uses), batched into ONE request
against the Hermes brain over the same OpenAI-compatible endpoint
config.yaml already configures (`OPENAI_BASE_URL`/`OPENAI_API_KEY`, model
`gpt-5.6-luna`), secrets resolved the same way every other secret in this
file is — never a plaintext key. At most `PROPOSE_MAPPINGS_MAX_SIGNATURES`
candidates per run: every `new` item with no `repo`/`verb` whose event has
been open longer than `proposeMappingsAgeDays` (policy knob, default 7 — a
signature younger than that may still be a one-off, and mapping it wastes a
whole investigate episode). The model returns strict JSON, one of three
shapes per signature: `ignore` (append to the ignore list — safe and cheap to
get wrong), `map` (append a rule — a wrong mapping costs at most one wasted
read-only `investigate` episode, bounded and visible), or `unsure` (leave
unmapped, and record the attempt so it is not re-billed on every run for
`PROPOSE_UNSURE_COOLDOWN_DAYS`). A `map` proposal's repo is re-validated
against the SAME discovery hermes-cc.sh's own `resolve_repo()` uses (must
resolve under `root`, must not be `deny`d) — never trusted from the model's
own claim alone, see BOUNDS THAT DO NOT MOVE. Every applied entry is stamped
`proposedAt`/`proposedBy: "triage-auto"` plus the model's one-line reason,
written back into config/triage-policy.json (preserving `_readme` and key
order), then `git add` + `git commit` — never `git push` — that ONE file, in
this repo's own checkout. Skipped outright, loudly, if that path already
carries a pending change, rather than sweeping an unrelated edit into an
auto-authored commit. A failed, timed-out, or unparseable model call is
logged to stderr and otherwise a no-op — this loop must never depend on it
succeeding, exactly like every other externally-visible call in this file.

`scripts/dispatch-sweep.py` closes the other half: when a dispatch tied to a
triage cluster (dispatches.origin_event_id) reaches a terminal status, it
calls `fold_dispatch_verdict()` below to fold the verdict onto every member's
row and the shared card — without waiting for this script's own next
10-minute pass.

MATCH TARGETS. `_match_targets()` builds TWO strings per event:
`f"{source}:{external_id}"` and `f"{source}:{normalize_title(title)}"`
(imported from watchdog-poll.py). A policy rule is tried against both, first
match wins. This matters most for state sources (`uk`) whose external_id is
an opaque UptimeKuma monitor id ("204") — unglobbable and unstable across a
monitor recreate — so `uk:macmini-dev-host-push` (the title-derived target) is
what makes that source mappable at all. For grouped sources (`slack_alert`,
`hermes_log`) the two targets are usually identical (their external_id already
IS normalize_title(title) — see aggregate_slack_batch()/poll_hermes_logs() in
watchdog-poll.py), so the second target is a harmless no-op there.

CLUSTERING. Multiple signatures can share one root cause — the shipped
example: `research-gateway job.reaped` and `audio-gateway podcast.failed` were
both `threshold: 0` in the same commit, fixed by the same two-line diff in the
same repo. `escalate()` groups every eligible `new` item BY RESOLVED REPO and
opens at most ONE sideclaw dispatch per repo per run (capped at 5 signatures
per brief; the rest wait for the next run), rather than one dispatch per item.
Cluster membership is DERIVED, never stored as its own column: every CARDED
triage_items row sharing a non-NULL `dispatch_job` value IS one cluster — a
dedicated `cluster_id` column would just duplicate that fact under a different
name. `_dissolve_cluster()` resets a split cluster's members to state `new`
(which drops them out of every cluster grouping — see CARDED STATES below),
but deliberately leaves `dispatch_job` itself set on those rows purely as a
cooldown anchor, not a live cluster pointer — see that function's own
docstring for why clearing it outright would let the escalate() call in the
very same run instantly re-fuse the pair it just split. The clustering is a
HYPOTHESIS from deterministic co-occurrence, never an assertion: the brief
tells the episode so explicitly and asks it to confirm or split it (see
DISSOLVE_MARKER below).

THE TWO EDGES THIS FIXES. `events.dispatch_id` (Phase 3 projection, added by
watchdog-poll.py, never written) and `dispatches.origin_event_id` (accepted by
hermes-cc.sh's `--origin-event`, never passed) were both always NULL before
this file existed. `--origin-event` takes exactly one events.id (one
dispatches row = one episode), so `escalate_cluster()` passes the cluster's
PRIMARY member there — hermes-cc.sh's own INSERT writes origin_event_id from
it, no second writer races `dispatches` for that column — and then does the
`UPDATE events SET dispatch_id=?` for EVERY member itself, which is the one
edge nothing else can write.

CARDED STATES. A card exists only once an item has left `new` — an item that
is mapped but hasn't yet crossed minOccurrences/minOpenMinutes, or is simply
unmapped, is carried silently (visible only in the once-a-day daily digest —
see maybe_post_daily_digest()). This is what keeps an empty or partial policy
from turning into dozens of cards of noise on day one. STATE_NOTE is
deliberately excluded too — see that state's own docstring.

VERB OUTCOMES. A policy rule can name `verb` instead of `repo` — routes to a
declared, code-side ALLOWLISTED local command instead of a sideclaw episode.
The rule names a KEY (e.g. `"env-check"`), never a command — a policy file
must never be able to name an arbitrary argv, the same closed-verb-set
principle hermes-cc.sh's own dispatch/status/list/merge/cancel verbs use.
Seeded with exactly one: `env-check` (hermes-ops.sh's ssh-based 1Password
ref-health probe), which op_refs_homelab/op_refs_vps route to. Cheaper than a
dispatch AND safer: a bare 1Password item name in the output doesn't match
sideclaw's `op://vault/item/field` secret-scan pattern the way a dispatched
verdict would, so the useful answer survives onto the card instead of being
withheld. Terminal state is `needs_human`; run_verbs() runs the command at
most once per item (see that function's own docstring for why no cooldown
tracking is needed) and the card's note IS the whole verdict — the dangling
item name plus the exact remediation, so no further investigation is needed.

DRY-RUN CONTRACT. `--dry-run` never touches Slack (no chat.postMessage/
chat.update) and never shells out to hermes-cc.sh — those two are the only
externally-visible actions this script can take. Every other step (ingest,
reopen/unsnooze, classify, resolve, dissolve bookkeeping) is local
bookkeeping against triage_items alone, idempotent and side-effect-free, so
it runs for real even under --dry-run: that is what lets a dry run against a
throwaway copy of watchdog.db print a meaningful "what would be carded and
dispatched" preview instead of nothing at all.

Source of truth: ~/SourceRoot/hermes-agent/scripts/triage.py
~/.hermes/scripts/ is itself a symlink to this directory (see make setup).
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HERMES_HOME = Path.home() / ".hermes"
DB_PATH = HERMES_HOME / "watchdog.db"

_env_cc_bin = os.environ.get("HERMES_CC_BIN")
HERMES_CC_BIN = Path(_env_cc_bin).expanduser() if _env_cc_bin else (HERMES_HOME / "scripts" / "hermes-cc.sh")

# Same env var name hermes-cc.sh itself honors for this file (HERMES_CC_REPOS_JSON)
# — one override reaches both the real dispatch and this script's own pre-check.
_env_repos_json = os.environ.get("HERMES_CC_REPOS_JSON")
DISPATCH_REPOS_JSON = (
    Path(_env_repos_json).expanduser() if _env_repos_json else (HERMES_HOME / "config" / "dispatch-repos.json")
)

_env_policy = os.environ.get("HERMES_TRIAGE_POLICY")
POLICY_PATH = Path(_env_policy).expanduser() if _env_policy else (HERMES_HOME / "config" / "triage-policy.json")

# Sources watchdog-poll.py already dedups that this loop acts on. github_*,
# hermes_cron, stray_skill are deliberately excluded — they are either
# already self-describing (a GitHub issue/PR IS the durable card) or
# governance-cadence, not the reactive-alert-channel firehose this exists to
# stop. op_refs_homelab/op_refs_vps ARE included: a dead 1Password ref blocks
# every future reseal of the mini's offline secrets cache (dotfiles' own
# CLAUDE.md §Secrets) — it must reach at least the unmapped digest, and
# routes to the `env-check` VERB (see VERB_ALLOWLIST below), never an
# episode. See docs/triage.md.
INGEST_SOURCES = ("slack_alert", "uk", "docker_homelab", "docker_vps", "hermes_log",
                   "op_refs_homelab", "op_refs_vps")

# The two INGEST_SOURCES that are grouped (upsert_grouped()-based, append-only)
# rather than state (reconcile()-based, disappearance-resolved) — mirrors
# watchdog-poll.py's own GROUPED_SOURCES, minus slack_update, which this loop
# never ingests. See resolve_quiet_grouped()/resolve_recovery_paired().
GROUPED_TRIAGE_SOURCES = ("slack_alert", "hermes_log")

STATE_NEW = "new"
STATE_INVESTIGATING = "investigating"
STATE_VERDICT = "verdict"
STATE_NEEDS_HUMAN = "needs_human"
STATE_PR_OPEN = "pr_open"
STATE_RESOLVED = "resolved"
STATE_SNOOZED = "snoozed"
STATE_IGNORED = "ignored"
# --- the auto-implement chain (verdict -> implement -> validate -> merge ->
# deploy -> verify), all downstream of a STATE_VERDICT item whose folded
# investigate verdict already said nextAction=implement at confidence=high.
# See maybe_auto_implement()/poll_implement_jobs()/poll_validation_jobs()/
# maybe_check_liveness() and their own docstrings for the state machine.
STATE_IMPLEMENTING = "implementing"      # implement episode dispatched, awaiting a PR
STATE_VALIDATING = "validating"          # a SECOND, different-model episode reviewing that PR's diff
STATE_MERGE_BLOCKED = "merge_blocked"    # implement failed, validation disagreed/errored, or merge itself refused
STATE_MERGED = "merged"                  # landed; no deploy configured/enabled for this repo
STATE_LIVENESS_PENDING = "liveness_pending"  # deployed; waiting on a positive liveness signal
# Terminal, like `ignored` — never escalates, never gets its own card — but
# UNLIKE `ignored`, it is NOT a recovery/known-benign match: it's a
# `slack_alert` row that doesn't look like a structured bot alert
# (ignoreUnstructuredSlackProse — see classify()) and therefore MIGHT be a
# human diagnosis that never got actioned (the shipped example: a Slack
# message naming the exact 1Password rate-limit root cause and its two-line
# fix, sitting unactioned). Silently dropping that into `ignored` would
# recreate the exact failure this whole redesign exists to kill. A `note`
# row surfaces once, under its own heading, in the daily digest — see
# maybe_post_daily_digest() — then is never touched again.
STATE_NOTE = "note"

# A card exists only for a row that has actually left `new` — see the module
# docstring's CARDED STATES paragraph. `snoozed` and `note` are deliberately
# excluded too: a human just silenced a snoozed row, and a `note` row is
# visible via the digest, not a card (see STATE_NOTE above).
#
# THE INVARIANT (2026-09-08 correction — a 13-card burst reopened this exact
# failure mode through the resolve path): a card is a conversation with the
# human about an item they were told about; a state change on an item they
# were never told about is not news. `STATE_RESOLVED` sits in this tuple
# because a CARDED item's resolution is real news (the human saw the problem,
# now sees it close) — but `resolved` is reachable from EVERY state including
# `new` (apply_resolutions()/resolve_quiet_grouped()/resolve_recovery_paired()
# all flip `new` straight to `resolved` on a quiet/disappeared signal that was
# never escalated), and an item whose whole life was `new -> resolved` was
# never told about in the first place. Being in CARDED_STATES only makes a row
# ELIGIBLE for a card — sync_card() below is where "already had one" is
# actually enforced (via `card_ts`), and that is the one place this rule is
# checked, rather than every caller having to re-derive it.
CARDED_STATES = (STATE_INVESTIGATING, STATE_VERDICT, STATE_NEEDS_HUMAN, STATE_PR_OPEN, STATE_RESOLVED,
                  STATE_IMPLEMENTING, STATE_VALIDATING, STATE_MERGE_BLOCKED, STATE_MERGED,
                  STATE_LIVENESS_PENDING)

# `triage_items.note` prefixes for the grouped-source resolve paths (see
# resolve_quiet_grouped()/resolve_recovery_paired()) plus the liveness path
# (see maybe_check_liveness()) — render_card_blocks() only surfaces `note` on
# a STATE_RESOLVED card when it starts with one of these, specifically so an
# ordinary event-driven resolve (apply_resolutions, which now clears `note`
# outright) never accidentally inherits stale text from an earlier phase.
# Deliberately NOT "fixed"/"resolved" wording for the first two — a service
# that is fully down also stops emitting, so silence alone is never proof of
# a fix; see both functions' own docstrings. LIVENESS_CONFIRMED_NOTE_PREFIX is
# the one genuine "this is actually fixed" claim in the file, because it is
# backed by a POSITIVE probe (maybe_check_liveness()'s own gatherer), not
# silence.
QUIET_RESOLVE_NOTE_PREFIX = "signal quiet since "
RECOVERY_PAIRED_NOTE_PREFIX = "recovery message observed: "
LIVENESS_CONFIRMED_NOTE_PREFIX = "liveness confirmed: "

STATE_EMOJI = {
    STATE_NEW: ":large_blue_circle:",
    STATE_INVESTIGATING: ":mag:",
    STATE_VERDICT: ":memo:",
    STATE_NEEDS_HUMAN: ":raising_hand:",
    STATE_PR_OPEN: ":twisted_rightwards_arrows:",
    STATE_RESOLVED: ":white_check_mark:",
    STATE_SNOOZED: ":zzz:",
    STATE_IMPLEMENTING: ":hammer_and_wrench:",
    STATE_VALIDATING: ":test_tube:",
    STATE_MERGE_BLOCKED: ":no_entry:",
    STATE_MERGED: ":rocket:",
    STATE_LIVENESS_PENDING: ":hourglass_flowing_sand:",
}

DEFAULT_CARD_CHANNEL = "C0BVDE5R562"  # #agents — see config/triage-policy.json
DEFAULT_MIN_OCCURRENCES = 3
DEFAULT_MIN_OPEN_MINUTES = 30
DEFAULT_COOLDOWN_HOURS = 6
# Grouped sources (slack_alert, hermes_log) never disappearance-resolve on
# their own — watchdog-poll.py's sweep_stale_grouped() only clears them
# after 7 idle DAYS (GROUPED_TTL_DAYS), which is deliberately housekeeping,
# not signal (its own docstring: silent specifically so a months-old row
# doesn't trigger a notification burst). 2h is the triage-side fix's
# default: comfortably past the 30-min watchdog-poll cadence (4+ consecutive
# misses before a false resolve) and short of either grouped source's own
# reminder window (6h/24h in REM_HOURS), so a signature that is GENUINELY
# still flapping gets re-noticed well before this would ever fire — while a
# fixed-and-deployed alert still closes the same day instead of sitting
# open for a week. See resolve_quiet_grouped().
DEFAULT_QUIET_RESOLVE_HOURS = 2.0

# Concurrency ceiling: simultaneously-open CLUSTERS (distinct dispatch_job
# values in state=investigating) this loop is allowed to have outstanding at
# once. Independent of the daily budget below — this bounds how many run AT
# THE SAME TIME, which matters because sideclaw itself has its own
# concurrency limits shared with every other dispatch source.
MAX_OPEN_INVESTIGATIONS = int(os.environ.get("TRIAGE_MAX_OPEN_INVESTIGATIONS", "3"))
# Dispatches opened per rolling UTC day BY THIS LOOP ONLY (counted via
# dispatches.origin_event_id IS NOT NULL, the same marker escalate_cluster()
# writes). Deliberately well under hermes-cc.sh's own 20/day so a triage storm
# can never starve interactive dispatch of its own budget. Counts CLUSTERS
# (one dispatch row), not member items.
DAILY_INVESTIGATE_BUDGET = int(os.environ.get("TRIAGE_DAILY_INVESTIGATE_BUDGET", "8"))
# A bare GET/POST against sideclaw (via hermes-cc.sh, which itself bounds its
# own HTTP calls) or Slack should never hang a 10-minute cron indefinitely.
SUBPROCESS_TIMEOUT = int(os.environ.get("TRIAGE_SUBPROCESS_TIMEOUT", "60"))
# How many signatures ride in one cluster's brief. The rest stay in `new` and
# wait for a later run — never dropped, never silently merged in anyway.
MAX_CLUSTER_SIGNATURES = 5

# hermes-cc.sh refuses a brief over this anyway (MAX_BRIEF_CHARS in that
# script) — capped here too, in Python, before the brief ever reaches a shell
# invocation, per CLAUDE.md's shell-conventions trap: this script pipes the
# brief to hermes-cc.sh on stdin rather than argv, so there is no `head -c`
# SIGPIPE hazard here, but the cap still belongs at the point the text is
# assembled, not left to the downstream script to enforce alone.
MAX_BRIEF_CHARS = 8000

# A cluster is a hypothesis, not an assertion (see module docstring). The
# brief asks the episode to say so, in these exact words, if it determines
# the grouped signatures do NOT share a root cause — a plain, case-sensitive
# substring check on the folded verdict's own text, never an LLM call here.
DISSOLVE_MARKER = "UNRELATED SIGNATURES"

SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
SLACK_UPDATE_URL = "https://slack.com/api/chat.update"
SECTION_TEXT_MAX = 3000  # Block Kit section text hard limit

DAILY_DIGEST_CURSOR_KEY = "triage_unmapped_digest_date"

# A policy rule names a KEY, never a command — a policy file must never be
# able to name an arbitrary argv. This is the closed allowlist code maps a
# `"verb"` rule outcome to; same closed-verb-set principle as hermes-cc.sh's
# own dispatch/status/list/merge/cancel verbs, applied to a single-purpose
# LOCAL health probe instead of a sideclaw episode — cheaper than a dispatch
# and safer: `env-check`'s bare 1Password item names don't match sideclaw's
# `op://vault/item/field` secret pattern the way a dispatched verdict would,
# so the useful answer survives onto the card instead of being withheld.
# hermes-ops.sh lives in this same directory (~/.hermes/scripts/ symlinks
# here) — no HERMES_HOME path needed.
_HERMES_OPS_BIN = Path(__file__).resolve().parent / "hermes-ops.sh"
VERB_ALLOWLIST: dict[str, list[str]] = {
    "env-check": [str(_HERMES_OPS_BIN), "env-check", "--json"],
}
# env-check runs TWO sequential ssh_run() probes (homelab, then vps), each
# individually bounded by hermes-ops.sh's own SSH_TIMEOUT=120 — so the outer
# bound here has to clear 240s, not just one call's worth, or this would kill
# a legitimately slow-but-healthy probe before hermes-ops.sh's own timeout
# ever got a chance to fire.
VERB_TIMEOUT = 260

# --- evidence commands — declared runtime-state probes, fenced into the brief -
#
# The episode this loop dispatches runs in a read-only sideclaw WORKTREE — it
# can see the repo, never the machine. All three real investigations this
# loop has run so far came back `nextAction: human` citing exactly that: no
# runtime state (var/health.json, watchdog-alerts.log, live OTel) was
# reachable from inside the checkout. A policy rule can now declare an
# `evidence` list — but, same closed-set principle as VERB_ALLOWLIST just
# above, ONLY a key from EVIDENCE_ALLOWLIST, never an arbitrary command: a
# policy file must never be able to name an arbitrary argv (or, here, an
# arbitrary probe). Unlike VERB_ALLOWLIST these four run IN-PROCESS rather
# than via subprocess.run on a fixed argv: three are bounded local file
# reads, and the fourth (kuma-push-last) needs both a secret
# (HOMELAB_API_KEY, which must never cross an argv/`ps` boundary) and
# per-cluster context (which UptimeKuma monitor actually fired) that a fixed
# argv has no way to carry. The closed-key-set contract itself — a policy
# file can only ever select one of these four, never invent a fifth — is
# still enforced the same way, at load_policy() time (see _valid_rule()).
EVIDENCE_ALLOWLIST: tuple[str, ...] = ("meteo-health", "gateway-starts", "hermes-log-tail", "kuma-push-last")

METEO_HEALTH_PATH = Path.home() / "SourceRoot" / "meteo" / "var" / "health.json"
GATEWAY_STARTS_LOG = HERMES_HOME / "gateway-starts.log"
HERMES_ERROR_LOG = HERMES_HOME / "logs" / "errors.log"
ALERTS_CHANNEL = "C0AS1LAUQ3C"  # #alerts — same channel watchdog-poll.py's slack_alert source reads

# Every evidence probe is read-only and bounded: a hard wall-clock timeout
# (a hung file read on a stale network mount, or a slow argo API call, must
# never stall a 10-minute cron) and a hard output cap. EVIDENCE_TOTAL_CAP_CHARS
# is well under MAX_BRIEF_CHARS so a 5-signature cluster (each pulling its own
# evidence) still leaves room for the rest of the brief — _build_evidence_block()
# enforces the remaining-budget cut described in the module docstring, never
# eating into the brief's own structure.
EVIDENCE_TIMEOUT = int(os.environ.get("TRIAGE_EVIDENCE_TIMEOUT", "20"))
EVIDENCE_CAP_CHARS = 1200
EVIDENCE_TOTAL_CAP_CHARS = 3200

# --- the auto-implement chain (steps 6-10: verdict -> implement -> validate ->
# merge -> deploy -> verify) ---------------------------------------------------
#
# STEP 7's whole point is a genuinely DIFFERENT model reviewing the implement
# episode's own diff — probed live against sideclaw before being hardcoded
# here: a throwaway `investigate` job at `model: "gpt-5.6-terra"` failed
# outright inside the Claude Code session with
# `[claude-code:unrecognized_model]` (session exit 1, not the usual harmless
# stderr telemetry line CLAUDE.md documents for that string elsewhere — this
# one actually crashed the session). `claude-opus-5[1m]` — still a different
# model from the claude-sonnet-5 default that writes the implement episode —
# ran a real Claude Code session and returned a structured verdict. Re-probe
# if this ever needs to change; do not guess a model id.
VALIDATION_MODEL = os.environ.get("TRIAGE_VALIDATION_MODEL", "claude-opus-5[1m]")

# Deterministic, not an LLM judgement by THIS file (see the module docstring's
# "no LLM call anywhere in this file" — the episode itself runs one, which is
# inherent to what "investigate" means). The validation brief instructs the
# episode to end with exactly one of these two phrases; poll_validation_jobs()
# does a plain substring check, the same technique DISSOLVE_MARKER already
# uses for the clustering hypothesis.
VALIDATION_CONFIRM_MARKER = "VALIDATION: CONFIRMED"
VALIDATION_DISAGREE_MARKER = "VALIDATION: DISAGREE"

# How long a deployed-but-unverified item waits for a positive liveness signal
# before this loop gives up and REOPENS it (see maybe_check_liveness()) rather
# than letting it sit "deployed" forever on a probe that never resolves either
# way. Comfortably longer than one 10-minute cron cycle so a slow-to-propagate
# change (HyperDX's own config apply, an alert re-evaluation window) isn't
# mistaken for a failure.
LIVENESS_WINDOW_HOURS = float(os.environ.get("TRIAGE_LIVENESS_WINDOW_HOURS", "2"))

HYPERDX_BASE = os.environ.get("TRIAGE_HYPERDX_BASE", "https://hyperdx.jkrumm.com")


def _gather_hyperdx_alert_state(expected: list[dict[str, Any]]) -> tuple[bool, str]:
    """Re-reads every expected alert's LIVE `threshold`/`thresholdType` from
    HyperDX's own `GET /api/api/v2/alerts` — the SAME REST endpoint
    vps/scripts/hyperdx-sync.sh's own `export`/`apply` already use (verified
    by reading that script, never a fabricated endpoint) — and asserts it
    matches what the merged diff set (captured at deploy time by
    hermes-cc.sh's `collect_expected_alerts()`, carried on
    triage_items.deploy_expect_json). Returns (ok, detail); `ok` is a genuine
    POSITIVE confirmation, never inferred from silence — see the module this
    is called from for why that distinction matters here specifically."""
    if not expected:
        return False, "no expected alert definitions were captured at deploy time"
    wp = _wp_module()
    if wp is None:
        return False, "watchdog-poll.py sibling module did not load — cannot reach HyperDX"
    token = wp.resolve_secret("HYPERDX_AGENT_ACCESS_KEY")
    if not token:
        return False, "HYPERDX_AGENT_ACCESS_KEY unresolved"
    req = urllib.request.Request(
        f"{HYPERDX_BASE}/api/api/v2/alerts", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError) as e:
        return False, f"HyperDX alerts fetch failed: {e}"
    live_by_name = {a.get("name"): a for a in (data.get("data") or []) if isinstance(a, dict)}
    mismatches = []
    for exp in expected:
        name = exp.get("name")
        live = live_by_name.get(name)
        if live is None:
            mismatches.append(f"{name}: not found live")
            continue
        if live.get("threshold") != exp.get("threshold") or live.get("thresholdType") != exp.get("thresholdType"):
            mismatches.append(f"{name}: live threshold={live.get('threshold')}/{live.get('thresholdType')} "
                              f"!= expected {exp.get('threshold')}/{exp.get('thresholdType')}")
    if mismatches:
        return False, "; ".join(mismatches)
    return True, f"{len(expected)} alert definition(s) verified live"


# Same closed-set principle as VERB_ALLOWLIST/EVIDENCE_ALLOWLIST above: a
# repo's `config/triage-policy.json` entry names a `liveness` KEY, never a
# probe. Seeded with exactly one, matching the one seeded `deploy` key.
LIVENESS_ALLOWLIST = {
    "hyperdx-alert-state": _gather_hyperdx_alert_state,
}

# --- propose_mappings() — the one LLM call in this file (see module docstring
# PROPOSE MAPPINGS) --------------------------------------------------------

# Same table/pattern DAILY_DIGEST_CURSOR_KEY already uses, but this one stores
# a full timestamp (not a bare date) so the gate is a genuine rolling 24h,
# checked before the model is ever called — a run that fires at 00:05 today
# must not fire again at 00:05 tomorrow just because the calendar date rolled.
PROPOSE_MAPPINGS_CURSOR_KEY = "triage_propose_mappings_last_run"

# How many candidates ride in ONE batched request. The rest simply wait for a
# later day's run — never dropped, never silently expanded into a second call
# (this loop makes at most one model call per run, full stop).
# A signature this many occurrences deep has proven it is not a one-off,
# whatever its age — see _propose_mapping_candidates() for why age alone
# is insufficient.
PROPOSE_MAPPINGS_MIN_OCCURRENCES = int(os.environ.get("TRIAGE_PROPOSE_MIN_OCCURRENCES", "5"))
PROPOSE_MAPPINGS_MAX_SIGNATURES = 25

# A batch of at most 25 short JSON decisions (one action + one one-line reason
# each) comfortably fits well under this; the cap exists so a misbehaving
# endpoint can't turn one daily maintenance call into an open-ended generation.
PROPOSE_MAPPINGS_MAX_OUTPUT_TOKENS = 2000

# The call itself, separate from SUBPROCESS_TIMEOUT (which bounds a hermes-cc.sh
# subprocess, not an HTTP request this file makes directly).
PROPOSE_MAPPINGS_TIMEOUT = int(os.environ.get("TRIAGE_PROPOSE_TIMEOUT", "90"))

# A signature younger than this may still be a one-off (a transient blip that
# resolves on its own before anyone would ever hand-map it) — mapping it this
# early wastes a whole investigate episode on something that might never
# recur. Policy knob: config/triage-policy.json's `proposeMappingsAgeDays`.
DEFAULT_PROPOSE_MAPPINGS_AGE_DAYS = 7.0

# How long an `unsure` verdict suppresses re-proposing THE SAME signature —
# long enough that a genuinely ambiguous signature is not re-billed into the
# model on every single day's run, short enough that it is reconsidered
# occasionally rather than permanently stuck.
PROPOSE_UNSURE_COOLDOWN_DAYS = 7.0

# Cheapest reasonable use of a model this file makes: chat_completions, no
# tools, temperature 0, over the SAME OpenAI-compatible endpoint config.yaml
# already points gpt-5.6-luna at (api_mode: chat_completions, e.g. the
# auxiliary blocks around OPENAI_BASE_URL/OPENAI_API_KEY) — never the
# Responses-API leg the main agent uses (codex_responses), which this file
# has no reason to touch.
PROPOSE_MAPPINGS_MODEL = os.environ.get("TRIAGE_PROPOSE_MODEL", "gpt-5.6-luna")

# Mirrors .env.tpl's own OPENAI_API_KEY ref exactly — never a plaintext key.
_OPENAI_API_KEY_REF = "op://common/anthropic/API_KEY"

TRIAGE_REPO_DIR = Path(__file__).resolve().parent.parent


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    payload_json TEXT,
    first_seen TEXT NOT NULL,
    notified_at TEXT,
    last_reminder_at TEXT,
    reminder_count INTEGER NOT NULL DEFAULT 0,
    resolved_at TEXT,
    UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_events_open ON events(source) WHERE resolved_at IS NULL;

CREATE TABLE IF NOT EXISTS dispatches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    tier TEXT NOT NULL,
    repo TEXT NOT NULL,
    brief TEXT NOT NULL,
    why TEXT,
    origin_channel TEXT,
    origin_thread_ts TEXT,
    origin_event_id INTEGER,
    status TEXT NOT NULL,
    verdict_json TEXT,
    artifact_url TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    reported_at TEXT
);

CREATE TABLE IF NOT EXISTS cursors (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS triage_items (
  event_id      INTEGER PRIMARY KEY REFERENCES events(id),
  signature     TEXT NOT NULL,
  repo          TEXT,
  verb          TEXT,
  state         TEXT NOT NULL,
  card_channel  TEXT,
  card_ts       TEXT,
  card_hash     TEXT,
  dispatch_job  TEXT,
  artifact_url  TEXT,
  occurrences   INTEGER NOT NULL DEFAULT 0,
  first_seen    TEXT,
  last_seen     TEXT,
  snoozed_until TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  note          TEXT,
  -- The auto-implement chain (steps 6-10) — see maybe_auto_implement() and
  -- its own siblings' docstrings for what writes/reads each column.
  implement_job      TEXT,  -- job id of the auto-dispatched `implement` episode
  validation_job     TEXT,  -- job id of the step-7 (different-model) review episode
  pr_url             TEXT,  -- the implement episode's own pull request, once opened
  deploy_expect_json TEXT,  -- expected alert def(s) captured at deploy time (hermes-cc.sh)
  liveness_deadline  TEXT,  -- maybe_check_liveness()'s reopen-if-not-confirmed-by window
  -- propose_mappings()'s own cooldown marker: the last time this signature's
  -- item was told `unsure` by the model, so it isn't re-billed daily — see
  -- PROPOSE_UNSURE_COOLDOWN_DAYS.
  propose_unsure_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_triage_state ON triage_items(state);
"""


def db_connect() -> sqlite3.Connection:
    """Same idiom as watchdog-poll.py/dispatch-sweep.py: sqlite3.connect +
    Row factory + an idempotent executescript, so this script works even on a
    fresh mini where neither of those has run yet. `events.dispatch_id` is
    copied from watchdog-poll.py's own additive migration — `CREATE TABLE IF
    NOT EXISTS` never adds a column to an already-existing table."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
    if "dispatch_id" not in cols:
        conn.execute("ALTER TABLE events ADD COLUMN dispatch_id INTEGER")
        conn.commit()
    ti_cols = {r["name"] for r in conn.execute("PRAGMA table_info(triage_items)").fetchall()}
    if "verb" not in ti_cols:
        conn.execute("ALTER TABLE triage_items ADD COLUMN verb TEXT")
        conn.commit()
    for col in ("implement_job", "validation_job", "pr_url", "deploy_expect_json", "liveness_deadline",
                "propose_unsure_at"):
        if col not in ti_cols:
            conn.execute(f"ALTER TABLE triage_items ADD COLUMN {col} TEXT")
            conn.commit()
    # Shared with hermes-cc.sh's own additive migration on this same table
    # (its db_py() adds them too) — added here as well so this file never
    # depends on hermes-cc.sh having run first against a given DB file.
    d_cols = {r["name"] for r in conn.execute("PRAGMA table_info(dispatches)").fetchall()}
    for col in ("validation_job_id", "validation_status"):
        if col not in d_cols:
            conn.execute(f"ALTER TABLE dispatches ADD COLUMN {col} TEXT")
            conn.commit()
    return conn


def _apply_db_override(argv: list[str]) -> None:
    """--db PATH, or the HERMES_CC_DB env var hermes-cc.sh/dispatch-sweep.py
    already honor (same table) — lets a test or a --dry-run inspection point
    this at a throwaway copy of the DB without touching the real
    ~/.hermes/watchdog.db."""
    global DB_PATH
    if "--db" in argv:
        idx = argv.index("--db")
        if idx + 1 < len(argv):
            DB_PATH = Path(argv[idx + 1]).expanduser()
            return
    env_override = os.environ.get("HERMES_CC_DB")
    if env_override:
        DB_PATH = Path(env_override).expanduser()


# --- Reused, not reimplemented: resolve_slack_token() + normalize_title() ----
#
# Both are loaded by path from their owning sibling script — the same
# mechanism the cron entry-point wrappers use (the filenames are not
# importable) — so a change to either is picked up here automatically rather
# than silently drifting out of sync. Each has a hand-mirrored fallback that
# only runs if the sibling script could not be loaded at all, so this file
# stays independently runnable.
_AGENTS_OVERVIEW_PATH = Path(__file__).resolve().parent / ("agents" + "-overview.py")
try:
    _ao_spec = importlib.util.spec_from_file_location("agents_overview_for_triage", _AGENTS_OVERVIEW_PATH)
    assert _ao_spec and _ao_spec.loader
    _agents_overview = importlib.util.module_from_spec(_ao_spec)
    _ao_spec.loader.exec_module(_agents_overview)
    resolve_slack_token = _agents_overview.resolve_slack_token
except Exception:  # pragma: no cover - defensive: keep triage.py independently runnable
    _SECRETS_RUN = Path.home() / ".local" / "bin" / "secrets-run"
    _SLACK_TOKEN_REF = "op://hermes/slack/bot-token"

    def resolve_slack_token() -> str:  # type: ignore[no-redef]
        """Mirrors agents-overview.py's resolve_slack_token() by hand — this
        branch only runs if that sibling script could not be loaded at all."""
        val = os.environ.get("SLACK_BOT_TOKEN", "")
        if val:
            return val
        env = os.environ.copy()
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "/usr/bin:/bin")
        try:
            r = subprocess.run(
                [str(_SECRETS_RUN), "read", _SLACK_TOKEN_REF],
                capture_output=True, text=True, timeout=15, env=env,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return r.stdout.strip() if r.returncode == 0 else ""

_WATCHDOG_POLL_PATH = Path(__file__).resolve().parent / ("watchdog" + "-poll.py")
try:
    _wp_spec = importlib.util.spec_from_file_location("watchdog_poll_for_triage", _WATCHDOG_POLL_PATH)
    assert _wp_spec and _wp_spec.loader
    _watchdog_poll = importlib.util.module_from_spec(_wp_spec)
    _wp_spec.loader.exec_module(_watchdog_poll)
    normalize_title = _watchdog_poll.normalize_title
except Exception:  # pragma: no cover - defensive: keep triage.py independently runnable
    import re as _re

    _DEDUP_NORMALIZE = _re.compile(r"[^a-z0-9]+")

    def normalize_title(text: str) -> str:  # type: ignore[no-redef]
        """Mirrors watchdog-poll.py's normalize_title() by hand — this branch
        only runs if that sibling script could not be loaded at all."""
        return _DEDUP_NORMALIZE.sub("-", text.lower()).strip("-")[:120]


def _slack_call(url: str, payload: dict[str, Any], token: str) -> tuple[bool, str | None]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError):
        return False, None
    ok = bool(data.get("ok"))
    if not ok:
        print(f"triage: slack call failed: {data.get('error', 'unknown')}", file=sys.stderr)
    return ok, data.get("ts")


def post_blocks(channel: str, blocks: list[dict[str, Any]], text_fallback: str, token: str) -> tuple[bool, str | None]:
    return _slack_call(
        SLACK_POST_URL,
        {"channel": channel, "blocks": blocks, "text": text_fallback, "unfurl_links": False},
        token,
    )


def update_blocks(channel: str, ts: str, blocks: list[dict[str, Any]], text_fallback: str,
                   token: str) -> tuple[bool, str | None]:
    return _slack_call(
        SLACK_UPDATE_URL,
        {"channel": channel, "ts": ts, "blocks": blocks, "text": text_fallback},
        token,
    )


# --- policy + repo-deny loading -----------------------------------------------

def _valid_rule(r: Any) -> bool:
    """A rule needs a `match` and EITHER `repo` (escalate to an episode) OR
    `verb` (run a declared local command — see VERB_ALLOWLIST). A `verb` not
    in the allowlist is rejected here, loudly, rather than silently matching
    nothing at classify() time — a policy file names a KEY, never a command,
    and a typo'd key is a policy bug worth surfacing immediately. An optional
    `evidence` list is validated the same way, against EVIDENCE_ALLOWLIST —
    see that constant's own comment."""
    if not (isinstance(r, dict) and r.get("match")):
        return False
    has_target = False
    if r.get("repo"):
        has_target = True
    else:
        verb = r.get("verb")
        if verb:
            if verb in VERB_ALLOWLIST:
                has_target = True
            else:
                print(f"triage: policy rule {r.get('match')!r} names verb {verb!r}, not in VERB_ALLOWLIST "
                      f"{sorted(VERB_ALLOWLIST)} — dropping this rule", file=sys.stderr)
    if not has_target:
        return False
    evidence = r.get("evidence")
    if evidence is not None:
        if not (isinstance(evidence, list) and all(isinstance(e, str) for e in evidence)):
            print(f"triage: policy rule {r.get('match')!r} has a malformed 'evidence' field (must be a "
                  f"list of strings) — dropping this rule", file=sys.stderr)
            return False
        unknown = [e for e in evidence if e not in EVIDENCE_ALLOWLIST]
        if unknown:
            print(f"triage: policy rule {r.get('match')!r} names evidence key(s) {unknown} not in "
                  f"EVIDENCE_ALLOWLIST {sorted(EVIDENCE_ALLOWLIST)} — dropping this rule", file=sys.stderr)
            return False
    return True


def load_policy() -> dict[str, Any]:
    try:
        data = json.loads(POLICY_PATH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"triage: could not read policy at {POLICY_PATH}: {e} — nothing will map or escalate this run",
              file=sys.stderr)
        data = {}
    return {
        "cardChannel": data.get("cardChannel") or DEFAULT_CARD_CHANNEL,
        "minOccurrences": int(data.get("minOccurrences") or DEFAULT_MIN_OCCURRENCES),
        "minOpenMinutes": int(data.get("minOpenMinutes") or DEFAULT_MIN_OPEN_MINUTES),
        "cooldownHours": int(data.get("cooldownHours") or DEFAULT_COOLDOWN_HOURS),
        "quietResolveHours": float(data.get("quietResolveHours") or DEFAULT_QUIET_RESOLVE_HOURS),
        "rules": [r for r in (data.get("rules") or []) if _valid_rule(r)],
        # `ignore` entries are usually a bare pattern string (hand-authored).
        # propose_mappings() instead appends a stamped object
        # ({"match", "proposedAt", "proposedBy", "reason"}) so an auto-added
        # entry carries its own provenance in the file itself — only the
        # `match` string is ever used for fnmatch, so both shapes classify()
        # identically.
        "ignore": [
            p if isinstance(p, str) else p["match"]
            for p in (data.get("ignore") or [])
            if isinstance(p, str) or (isinstance(p, dict) and isinstance(p.get("match"), str))
        ],
        # See CLAUDE.md/docs/triage.md — filters Hermes's OWN pre-silencing
        # conversational replies that watchdog-poll.py ingested from #alerts
        # as if they were alerts (297 signatures, ~30 permanently open) —
        # routed to STATE_NOTE, never STATE_IGNORED (see classify()).
        "ignoreUnstructuredSlackProse": bool(data.get("ignoreUnstructuredSlackProse")),
        # Per-repo merge/deploy/liveness policy (autoMergePaths, noCiRequired,
        # deploy, autoDeploy, liveness) — hermes-cc.sh's `merge` reads its own
        # half straight from this same file; this file only reads `liveness`
        # (maybe_check_liveness()). Malformed entries are left as-is here and
        # validated at the point each key is actually used, matching `verb`/
        # `evidence`'s own load_policy()-time-vs-use-time split above.
        "repos": data.get("repos") if isinstance(data.get("repos"), dict) else {},
        # propose_mappings()'s own age gate — see DEFAULT_PROPOSE_MAPPINGS_AGE_DAYS's
        # own comment for why a signature younger than this is left alone.
        "proposeMappingsAgeDays": float(data.get("proposeMappingsAgeDays") or DEFAULT_PROPOSE_MAPPINGS_AGE_DAYS),
    }


def _card_channel(policy: dict[str, Any]) -> str:
    return policy["cardChannel"]


def _denied_repos() -> set[str]:
    """The dispatch bridge's own deny list (config/dispatch-repos.json) —
    checked here BEFORE ever shelling out to hermes-cc.sh, so a stale or
    mistaken policy rule naming a denied repo produces a loud stderr line and
    zero dispatches, never a dispatch that hermes-cc.sh then refuses anyway."""
    try:
        data = json.loads(DISPATCH_REPOS_JSON.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    deny = data.get("deny")
    return set(deny) if isinstance(deny, list) else set()


def _match_targets(event_row: sqlite3.Row) -> list[str]:
    """Two candidate strings a policy rule can match against, in order: the
    raw `source:external_id` (works for grouped/self-describing sources), and
    `source:normalize_title(title)` (works for a state source like `uk`,
    whose external_id is an opaque, unglobbable monitor id — see the module
    docstring's MATCH TARGETS paragraph)."""
    source = event_row["source"]
    external_id = event_row["external_id"] or ""
    targets = [f"{source}:{external_id}"]
    norm = normalize_title(event_row["title"] or "")
    if norm:
        alt = f"{source}:{norm}"
        if alt not in targets:
            targets.append(alt)
    return targets


def _fnmatch_any(targets: list[str], patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(t, p) for t in targets for p in patterns)


def _match_rule(targets: list[str], rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    """First rule (already validated by _valid_rule — `repo` XOR a
    VERB_ALLOWLIST-known `verb`) whose `match` fnmatches any target. The
    caller reads whichever of `repo`/`verb` is present to decide the
    outcome — see classify()."""
    for rule in rules:
        for t in targets:
            if fnmatch.fnmatch(t, rule["match"]):
                return rule
    return None


# `[`  — UptimeKuma's own bracketed monitor-name format: "[X] [:red_circle: Down] ..."
# emoji — HyperDX/argo-alert style: "🚨 ...", "✅ ...", "⚠️ ...", "*⚠️ ..." (bold mrkdwn)
_BOT_ALERT_PREFIXES = ("[", "\U0001F6A8", "✅", "⚠️", "*⚠️")


def _looks_like_bot_alert(title: str) -> bool:
    return (title or "").lstrip().startswith(_BOT_ALERT_PREFIXES)


# --- small helpers -------------------------------------------------------------

def _now_iso(now: dt.datetime) -> str:
    return now.isoformat()


def _safe_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _fmt_ts(value: str | None) -> str:
    parsed = _parse_ts(value)
    if parsed is None:
        return value or "?"
    return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _age_minutes(first_seen: str | None, now: dt.datetime) -> float:
    parsed = _parse_ts(first_seen)
    if parsed is None:
        return 0.0
    return (now - parsed).total_seconds() / 60.0


def _signature(event_row: sqlite3.Row) -> str:
    return f"{event_row['source']}:{event_row['external_id']}"


def _get_event(conn: sqlite3.Connection, event_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()


def _get_item(conn: sqlite3.Connection, event_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM triage_items WHERE event_id=?", (event_id,)).fetchone()


# --- 1. ingest -------------------------------------------------------------

def ingest(conn: sqlite3.Connection, now: dt.datetime) -> None:
    """Upsert one triage_items row per open ingest-source event. Occurrences
    and last_seen refresh every run; repo/state are left alone on an existing
    row — classify() owns those, so a re-run never clobbers an escalation in
    progress."""
    placeholders = ",".join("?" * len(INGEST_SOURCES))
    rows = conn.execute(
        f"SELECT * FROM events WHERE resolved_at IS NULL AND source IN ({placeholders})",
        INGEST_SOURCES,
    ).fetchall()
    now_iso = _now_iso(now)
    for ev in rows:
        event_id = ev["id"]
        payload = _safe_json(ev["payload_json"])
        occurrences = payload.get("batch_count")
        if not isinstance(occurrences, int):
            occurrences = int(ev["reminder_count"] or 0) + 1
        last_seen = ev["last_reminder_at"] or ev["notified_at"] or ev["first_seen"] or now_iso
        existing = _get_item(conn, event_id)
        if existing is None:
            conn.execute(
                "INSERT INTO triage_items(event_id, signature, repo, state, occurrences, "
                "first_seen, last_seen, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (event_id, _signature(ev), None, STATE_NEW, occurrences,
                 ev["first_seen"], last_seen, now_iso, now_iso),
            )
        else:
            conn.execute(
                "UPDATE triage_items SET occurrences=?, last_seen=?, updated_at=? WHERE event_id=?",
                (occurrences, last_seen, now_iso, event_id),
            )
    conn.commit()


def reopen_if_needed(conn: sqlite3.Connection, now: dt.datetime) -> None:
    """A grouped or state source reuses the SAME events.id across a
    resolve -> recur cycle (UNIQUE(source, external_id), resolved_at reset to
    NULL on reopen) — so a triage_items row stuck in `resolved` for an event
    that has since reopened would otherwise sit invisible forever. Reopening
    to `new` (never clearing artifact_url/dispatch_job) is exactly what lets
    the next escalation's brief say "a PR already exists for this signature"
    instead of re-discovering it from scratch."""
    rows = conn.execute(
        "SELECT ti.event_id FROM triage_items ti JOIN events e ON e.id = ti.event_id "
        "WHERE ti.state=? AND e.resolved_at IS NULL",
        (STATE_RESOLVED,),
    ).fetchall()
    now_iso = _now_iso(now)
    for row in rows:
        conn.execute(
            "UPDATE triage_items SET state=?, updated_at=? WHERE event_id=?",
            (STATE_NEW, now_iso, row["event_id"]),
        )
    conn.commit()


def unsnooze_if_expired(conn: sqlite3.Connection, now: dt.datetime) -> None:
    now_iso = _now_iso(now)
    conn.execute(
        "UPDATE triage_items SET state=?, snoozed_until=NULL, updated_at=? "
        "WHERE state=? AND snoozed_until IS NOT NULL AND snoozed_until<=?",
        (STATE_NEW, now_iso, STATE_SNOOZED, now_iso),
    )
    conn.commit()


def apply_resolutions(conn: sqlite3.Connection, now: dt.datetime) -> None:
    # STATE_NOTE is excluded alongside IGNORED/SNOOZED: it is terminal by
    # design (see that state's docstring) and must never flip to RESOLVED,
    # which IS a carded state — an unstructured-prose row must never get a
    # card, including a one-time "resolved" one.
    rows = conn.execute(
        "SELECT ti.event_id FROM triage_items ti JOIN events e ON e.id = ti.event_id "
        "WHERE e.resolved_at IS NOT NULL AND ti.state NOT IN (?, ?, ?, ?)",
        (STATE_RESOLVED, STATE_IGNORED, STATE_SNOOZED, STATE_NOTE),
    ).fetchall()
    now_iso = _now_iso(now)
    for row in rows:
        # note=NULL: a genuine event-driven resolve has no need to retain
        # whatever text a PRIOR investigation phase left in `note` (a
        # needs_human blocker, an env-check remediation, ...) — and clearing
        # it here is also what stops a stale QUIET_RESOLVE_NOTE_PREFIX/
        # RECOVERY_PAIRED_NOTE_PREFIX note from a much earlier quiet-resolve
        # surviving a reopen -> genuine fix -> resolve cycle and rendering
        # under render_card_blocks()'s STATE_RESOLVED branch as if it were
        # still current.
        conn.execute(
            "UPDATE triage_items SET state=?, note=NULL, updated_at=? WHERE event_id=?",
            (STATE_RESOLVED, now_iso, row["event_id"]),
        )
    conn.commit()


def _quiet_resolve_hours(policy: dict[str, Any]) -> float:
    return float(policy.get("quietResolveHours") or DEFAULT_QUIET_RESOLVE_HOURS)


# States a grouped item must NOT be in to be eligible for either resolve path
# below — same terminal exclusions as apply_resolutions(), PLUS `investigating`:
# an open dispatch is already in flight, so a quiet timer or a recovery
# message racing dispatch-sweep.py's own fold_dispatch_verdict() would be
# premature. Let the investigation finish; either resolve path can still
# close it out on THAT state (verdict/needs_human/pr_open) on a later run.
_GROUPED_RESOLVE_EXCLUDED_STATES = (STATE_RESOLVED, STATE_IGNORED, STATE_SNOOZED, STATE_NOTE,
                                     STATE_INVESTIGATING)


def resolve_recovery_paired(conn: sqlite3.Connection, policy: dict[str, Any], now: dt.datetime,
                             *, dry_run: bool) -> None:
    """The stronger of the two grouped-source resolve paths (see
    resolve_quiet_grouped() for the fallback): a `✅ <same alert text>`
    recovery message is itself a positive signal that the paired `🚨` alert
    cleared, strictly better than waiting out a quiet window — a service
    that is fully DOWN also stops emitting, so silence alone can never tell
    the two apart, but an explicit recovery message can.

    This is cheap specifically because HyperDX's own webhook posts the
    IDENTICAL alert text with only the leading glyph flipped (see the brief
    that shipped this: "the titles differ only by the leading glyph"), and
    normalize_title() already strips every non-alnum character — including
    both glyphs — so a `✅ research-gateway job.reaped >= 1 (15m)` message
    normalizes to the SAME string as `🚨 research-gateway job.reaped >= 1
    (15m)`. For a grouped source that string already IS the event's own
    stable `external_id` (see docs/triage.md's MATCH TARGETS — computed once
    at first-batch time and never re-derived), so no new text-matching
    scheme is needed: one fresh #alerts fetch, one dict lookup per
    candidate.

    This CANNOT be read back out of `events`/`payload_json` — upsert_grouped()
    only retains one title (whichever batch's group needed to emit) and never
    a per-occurrence history (see docs/triage.md's own note on that), so a ✅
    that lands in the same 30-min batch as its 🚨 counterpart is silently
    folded into a bumped `batch_count` with no trace of which glyph it was.
    Reading live #alerts instead of `events` is what makes this possible at
    all — and it stays cheap because it is ONE fetch per triage run
    (poll_slack_messages's own single call), shared across every open
    slack_alert candidate via one dict, not one call per item."""
    if dry_run:
        # Mirrors escalate_cluster()/run_verbs(): --dry-run makes NO outbound
        # call, Slack reads included, so a preview against a throwaway DB
        # copy never depends on live credentials or network.
        placeholders = ",".join("?" * len(_GROUPED_RESOLVE_EXCLUDED_STATES))
        candidates = conn.execute(
            f"SELECT ti.event_id FROM triage_items ti JOIN events e ON e.id = ti.event_id "
            f"WHERE e.source='slack_alert' AND e.resolved_at IS NULL AND ti.state NOT IN ({placeholders})",
            _GROUPED_RESOLVE_EXCLUDED_STATES,
        ).fetchall()
        if candidates:
            print(f"[dry-run] would check {len(candidates)} open slack_alert item(s) against live "
                  f"#alerts for a ✅ recovery pairing (skipped under --dry-run)")
        return

    wp = _wp_module()
    if wp is None:
        return
    token = wp.resolve_secret("HOMELAB_API_KEY")
    if not token:
        return
    msgs, _latest, ok = wp.poll_slack_messages({"HOMELAB_API_KEY": token}, ALERTS_CHANNEL, None,
                                                skip_uk_push=True)
    if not ok or not msgs:
        return
    latest_by_key: dict[str, tuple[str, str]] = {}
    for m in msgs:
        text = (m.get("payload") or {}).get("text") or m.get("title") or ""
        key = normalize_title(text)
        if not key:
            continue
        ts = m.get("external_id") or "0"
        prev = latest_by_key.get(key)
        if prev is None or ts > prev[0]:
            latest_by_key[key] = (ts, text)

    placeholders = ",".join("?" * len(_GROUPED_RESOLVE_EXCLUDED_STATES))
    rows = conn.execute(
        f"SELECT ti.event_id, e.external_id FROM triage_items ti JOIN events e ON e.id = ti.event_id "
        f"WHERE e.source='slack_alert' AND e.resolved_at IS NULL AND ti.state NOT IN ({placeholders})",
        _GROUPED_RESOLVE_EXCLUDED_STATES,
    ).fetchall()
    now_iso = _now_iso(now)
    for row in rows:
        match = latest_by_key.get(row["external_id"])
        if match is None:
            continue
        _ts, text = match
        if not text.lstrip().startswith("✅"):
            continue
        note = f"{RECOVERY_PAIRED_NOTE_PREFIX}{text.strip()[:200]}"
        conn.execute(
            "UPDATE triage_items SET state=?, note=?, updated_at=? WHERE event_id=?",
            (STATE_RESOLVED, note, now_iso, row["event_id"]),
        )
    conn.commit()


def resolve_quiet_grouped(conn: sqlite3.Connection, policy: dict[str, Any], now: dt.datetime) -> None:
    """The fallback half of grouped-source resolution (see
    resolve_recovery_paired() for the stronger positive-signal path):
    GROUPED_TRIAGE_SOURCES (slack_alert, hermes_log) never disappearance-
    resolve on their own event lifecycle — watchdog-poll.py's own
    sweep_stale_grouped() only clears them after 7 idle DAYS, deliberately
    housekeeping rather than signal (its own docstring: silent specifically
    so a months-old row doesn't trigger a notification burst). This is the
    triage-SIDE fix: a row whose underlying event has produced no new
    occurrence in `quietResolveHours` (DEFAULT_QUIET_RESOLVE_HOURS's own
    comment justifies the default) flips to `resolved` here — a purely
    local state transition that never touches `events.resolved_at` (that
    column stays owned end to end by watchdog-poll.py, per this file's own
    brief: "Do not change watchdog-poll.py's own sweep_stale_grouped").

    No new column is needed to track "quiet since": `events.last_reminder_at`
    / `notified_at` / `first_seen` (the same idle anchor sweep_stale_grouped()
    itself uses) only ADVANCES when watchdog-poll.py re-stamps the row on a
    fresh occurrence (see upsert_grouped()) — so a value that has stopped
    changing already IS the quiet duration.

    Deliberately never claims a fix: render_card_blocks() only ever shows
    this as "signal quiet since <time>" (QUIET_RESOLVE_NOTE_PREFIX) — a
    service that is fully down also stops emitting, so silence alone is
    never proof of anything beyond silence. Pure local bookkeeping (no
    Slack, no dispatch), so — like apply_resolutions()/classify() — this
    runs for real even under --dry-run; only the eventual card sync
    respects `dry_run` (see run()'s own sync_card() call)."""
    quiet_hours = _quiet_resolve_hours(policy)
    placeholders_sources = ",".join("?" * len(GROUPED_TRIAGE_SOURCES))
    placeholders_states = ",".join("?" * len(_GROUPED_RESOLVE_EXCLUDED_STATES))
    rows = conn.execute(
        f"SELECT ti.event_id, e.last_reminder_at, e.notified_at, e.first_seen "
        f"FROM triage_items ti JOIN events e ON e.id = ti.event_id "
        f"WHERE e.source IN ({placeholders_sources}) AND e.resolved_at IS NULL "
        f"AND ti.state NOT IN ({placeholders_states})",
        (*GROUPED_TRIAGE_SOURCES, *_GROUPED_RESOLVE_EXCLUDED_STATES),
    ).fetchall()
    now_iso = _now_iso(now)
    for row in rows:
        anchor_raw = row["last_reminder_at"] or row["notified_at"] or row["first_seen"]
        quiet_since = _parse_ts(anchor_raw)
        if quiet_since is None:
            continue
        if (now - quiet_since).total_seconds() < quiet_hours * 3600:
            continue
        note = (f"{QUIET_RESOLVE_NOTE_PREFIX}{_fmt_ts(anchor_raw)} — no new occurrence for "
                f"{quiet_hours:g}h. This closes the item on silence alone; it is NOT a confirmed "
                f"fix, and the signature reopens automatically the moment it recurs.")
        conn.execute(
            "UPDATE triage_items SET state=?, note=?, updated_at=? WHERE event_id=?",
            (STATE_RESOLVED, note, now_iso, row["event_id"]),
        )
    conn.commit()


def classify(conn: sqlite3.Connection, policy: dict[str, Any], now: dt.datetime) -> set[str]:
    """Resolve `repo`/`verb` (fnmatch against BOTH match targets — see
    _match_targets()) and apply, in order: the explicit `ignore` list (same
    targets — a deliberate human call that THIS signature is a genuine
    recovery or known-benign pattern, checked first so it always wins), then
    the structural `ignoreUnstructuredSlackProse` fallback (routes to
    STATE_NOTE, never STATE_IGNORED — see that state's own docstring for why
    silently dropping unstructured #alerts prose would recreate the exact
    bug this file exists to kill), then rule matching. Only ever touches a
    row still in state `new`. Returns every signature that matched no rule
    this run, for the once-a-day digest."""
    rows = conn.execute(
        "SELECT event_id, signature, repo, verb FROM triage_items WHERE state=?", (STATE_NEW,)
    ).fetchall()
    unmapped: set[str] = set()
    now_iso = _now_iso(now)
    for row in rows:
        event_row = _get_event(conn, row["event_id"])
        if event_row is None:
            continue
        targets = _match_targets(event_row)

        if _fnmatch_any(targets, policy["ignore"]):
            conn.execute(
                "UPDATE triage_items SET state=?, updated_at=? WHERE event_id=?",
                (STATE_IGNORED, now_iso, row["event_id"]),
            )
            continue

        if policy["ignoreUnstructuredSlackProse"] and event_row["source"] == "slack_alert" \
                and not _looks_like_bot_alert(event_row["title"]):
            conn.execute(
                "UPDATE triage_items SET state=?, updated_at=? WHERE event_id=?",
                (STATE_NOTE, now_iso, row["event_id"]),
            )
            continue

        if row["repo"] is None and row["verb"] is None:
            rule = _match_rule(targets, policy["rules"])
            if rule is not None and rule.get("repo"):
                conn.execute(
                    "UPDATE triage_items SET repo=?, updated_at=? WHERE event_id=?",
                    (rule["repo"], now_iso, row["event_id"]),
                )
            elif rule is not None and rule.get("verb"):
                conn.execute(
                    "UPDATE triage_items SET verb=?, updated_at=? WHERE event_id=?",
                    (rule["verb"], now_iso, row["event_id"]),
                )
            else:
                unmapped.add(row["signature"])
    conn.commit()
    return unmapped


# --- clustering ----------------------------------------------------------------

def _cluster_groups(conn: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    """Every carded (state in CARDED_STATES) triage_items row, grouped by
    `dispatch_job` — the derived cluster key (see module docstring). A row
    with no dispatch_job (e.g. `resolved` without ever having escalated) is
    its own singleton group keyed by its own event_id."""
    placeholders = ",".join("?" * len(CARDED_STATES))
    rows = conn.execute(
        f"SELECT * FROM triage_items WHERE state IN ({placeholders}) ORDER BY event_id",
        CARDED_STATES,
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        key = row["dispatch_job"] or f"solo:{row['event_id']}"
        groups.setdefault(key, []).append(row)
    return groups


def _count_open_investigation_clusters(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT count(DISTINCT dispatch_job) c FROM triage_items WHERE state=? AND dispatch_job IS NOT NULL",
        (STATE_INVESTIGATING,),
    ).fetchone()
    return int(row["c"]) if row else 0


def _investigate_dispatches_today(conn: sqlite3.Connection, now: dt.datetime) -> int:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    row = conn.execute(
        "SELECT count(*) c FROM dispatches WHERE origin_event_id IS NOT NULL AND created_at >= ?",
        (start,),
    ).fetchone()
    return int(row["c"]) if row else 0


def _sibling_open_items(conn: sqlite3.Connection, repo: str, exclude_event_ids: list[int],
                         limit: int = 5) -> list[dict[str, str]]:
    placeholders = ",".join("?" * len(exclude_event_ids)) if exclude_event_ids else "-1"
    rows = conn.execute(
        f"SELECT ti.signature, e.title FROM triage_items ti JOIN events e ON e.id = ti.event_id "
        f"WHERE ti.repo=? AND ti.event_id NOT IN ({placeholders}) AND ti.state NOT IN (?, ?) "
        f"ORDER BY ti.updated_at DESC LIMIT ?",
        (repo, *exclude_event_ids, STATE_RESOLVED, STATE_IGNORED, limit),
    ).fetchall()
    return [{"signature": r["signature"], "title": r["title"]} for r in rows]


def _recent_raw_texts(event_row: sqlite3.Row) -> list[str]:
    """Best-effort distinct raw text for the brief, capped at 3. The
    watchdog schema does not retain a history of individual occurrences
    beyond a grouped signature's `first_text`/`first_line` — upsert_grouped
    rewrites payload_json in place on every poll (see docs/triage.md) — so
    this surfaces what is actually available (the current title, plus the
    grouped payload's first_text/first_line if distinct) rather than
    fabricating a 3-item history that doesn't exist in the DB."""
    out: list[str] = []
    title = (event_row["title"] or "").strip()
    if title:
        out.append(title)
    payload = _safe_json(event_row["payload_json"])
    for key in ("first_text", "first_line"):
        val = payload.get(key)
        val = val.strip() if isinstance(val, str) else ""
        if val and val not in out:
            out.append(val)
    return out[:3]


def _cap_brief(text: str) -> str:
    if len(text) <= MAX_BRIEF_CHARS:
        return text
    return text[: MAX_BRIEF_CHARS - 1].rstrip() + "…"


# --- evidence gathering — declared runtime-state probes (see EVIDENCE_ALLOWLIST) --

def _cap_evidence(text: str, cap: int) -> str:
    text = text or ""
    if len(text) <= cap:
        return text
    return text[: max(cap - 1, 0)].rstrip() + "…"


def _wp_module() -> Any | None:
    """The sibling watchdog-poll.py module, if it loaded (see the module-level
    try/except above `normalize_title` for why it might not have) — used only
    by evidence gatherers that need its already-proven resolve_secret()/
    poll_slack_messages(), never re-implemented here. None (never raises) if
    that sibling load failed, so a broken import degrades one evidence key,
    not the whole run."""
    return globals().get("_watchdog_poll")


def _run_bounded(fn: Any, *args: Any, timeout: int = EVIDENCE_TIMEOUT) -> tuple[bool, str]:
    """Runs fn(*args) with a hard wall-clock timeout. Every evidence gatherer
    below is read-only and side-effect-free, so this is the in-process
    equivalent of the `timeout=` subprocess.run() already gives VERB_ALLOWLIST
    commands — a hang (a stuck network mount, a slow argo API call) can't
    stall a 10-minute cron. A timeout or ANY exception folds into a returned
    error string rather than raising — a failing evidence command must never
    abort the run (see the module docstring's DRY-RUN/loop contract)."""
    # NOT `with ThreadPoolExecutor(...)`: its __exit__ calls shutdown(wait=True),
    # which blocks until the worker thread finishes — so a gatherer that hung
    # would sail straight past `timeout` and stall the loop anyway, defeating the
    # whole point of this function. shutdown(wait=False) lets a stuck thread keep
    # running (it is read-only and side-effect-free by contract, and the process
    # is a short-lived cron invocation that will exit) while the caller moves on.
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(fn, *args)
        try:
            return True, fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return False, f"timed out after {timeout}s"
        except Exception as e:  # noqa: BLE001 - must never raise into the caller
            return False, f"{type(e).__name__}: {e}"
    finally:
        ex.shutdown(wait=False)


def _gather_meteo_health(_event_rows: list[sqlite3.Row]) -> str:
    """meteo's own health probe (var/health.json, written by its own
    heartbeat) — the exact gap the meteo episode named: a repo checkout has
    no runtime state at all. Summarized (ok/heartbeat/timestamp + failing
    checks only), not dumped raw — the file runs ~40 checks and dumping all
    of them would blow the per-key cap on a mostly-healthy day for no
    benefit."""
    try:
        data = json.loads(METEO_HEALTH_PATH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return f"could not read {METEO_HEALTH_PATH}: {e}"
    if not isinstance(data, dict):
        return f"{METEO_HEALTH_PATH} did not contain a JSON object"
    checks = data.get("checks")
    checks = checks if isinstance(checks, list) else []
    bad = [c for c in checks if isinstance(c, dict) and not c.get("ok")]
    lines = [f"ok={data.get('ok')} heartbeat={data.get('heartbeat')!r} as of {data.get('timestamp')}",
             f"{len(bad)}/{len(checks)} checks failing"]
    for c in bad[:10]:
        lines.append(f"- {c.get('name')}: {c.get('detail')}")
    return "\n".join(lines)


def _gather_gateway_starts(_event_rows: list[sqlite3.Row]) -> str:
    """The last few recorded Hermes gateway process starts — gateway-starts.log
    is an append-only ledger of one UTC epoch per start (gateway/status.py's
    record_start_and_check_storm()), which happens to sit outside every repo
    worktree (~/.hermes/, not ~/SourceRoot/hermes-agent/) — the one source
    the hermes-agent episode could already see, by accident, per the brief
    that shipped this. This makes it reliable rather than incidental."""
    try:
        lines = GATEWAY_STARTS_LOG.read_text().splitlines()
    except OSError as e:
        return f"could not read {GATEWAY_STARTS_LOG}: {e}"
    out = []
    for raw in lines[-5:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            ts = dt.datetime.fromtimestamp(float(raw), dt.timezone.utc)
        except ValueError:
            continue
        out.append(ts.strftime("%Y-%m-%d %H:%M UTC"))
    if not out:
        return f"{GATEWAY_STARTS_LOG} has no parseable start timestamps"
    return f"last {len(out)} gateway start(s) (UTC): " + "; ".join(out)


def _current_gateway_start_local() -> dt.datetime | None:
    """The latest recorded gateway start, in LOCAL system time — errors.log's
    own lines are unqualified local timestamps (Python logging's default), so
    the slice boundary below has to be computed in the same zone or the
    string comparison in _gather_hermes_log_tail() is silently off by the
    system's UTC offset."""
    try:
        lines = GATEWAY_STARTS_LOG.read_text().splitlines()
    except OSError:
        return None
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            return dt.datetime.fromtimestamp(float(raw))
        except ValueError:
            continue
    return None


def _gather_hermes_log_tail(_event_rows: list[sqlite3.Row]) -> str:
    """Tail of Hermes's own error log, SLICED AT the current gateway process
    start — skills/hermes-gateway/SKILL.md Rule 0 exists because this was
    gotten wrong once already: agent.log/errors.log are not rotated per
    process, so an unsliced tail mixes a dead incarnation's errors with the
    live one, and a 48-hour-old burst got reported as a live fault. That
    skill establishes the boundary via a live PID + `ps -o lstart=`; this
    script isn't the gateway process and has no business inspecting
    launchd/pgrep, so gateway-starts.log's own append-only ledger (one epoch
    per start) stands in for the same boundary."""
    start = _current_gateway_start_local()
    try:
        raw_lines = HERMES_ERROR_LOG.read_text(errors="replace").splitlines()
    except OSError as e:
        return f"could not read {HERMES_ERROR_LOG}: {e}"
    ts_re = getattr(_wp_module(), "LOG_TS_RE", None) or re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
    if start is None:
        sliced = raw_lines
        note = "no gateway-starts.log boundary found — showing the unsliced tail"
    else:
        boundary = start.strftime("%Y-%m-%d %H:%M:%S")
        idx = None
        for i, ln in enumerate(raw_lines):
            m = ts_re.match(ln)
            if m and m.group(1) >= boundary:
                idx = i
                break
        sliced = raw_lines[idx:] if idx is not None else []
        note = f"sliced at current gateway start {boundary} (local)"
    tail = sliced[-40:]
    if not tail:
        return f"{note}; zero lines since the current process started — a real finding, not a gap"
    return f"{note}; last {len(tail)} line(s):\n" + "\n".join(tail)


_BRACKET_PREFIX_RE = re.compile(r"^\[([^\]]+)\]")


def _gather_kuma_push_last(event_rows: list[sqlite3.Row]) -> str:
    """The most recent `[<monitor name>] ...` message text from #alerts for
    whichever member of this cluster is a `uk` (UptimeKuma) signal. The gap
    this fixes: watchdog-poll.py's own `uk` event payload is literally
    `{"type", "status"}` (see poll_uk()), and the 16-component heartbeat line
    (e.g. `FAIL: disk 90% used (max 90%)`) exists ONLY in the raw Slack
    text — poll_slack_messages() deliberately DROPS it via `skip_uk_push`
    before it ever reaches `events`, and argo's own monitor endpoint doesn't
    carry it either. Reuses watchdog-poll.py's own proven Slack-fetch path
    (same #alerts channel, same HOMELAB_API_KEY) rather than a second HTTP
    mechanism against the raw Slack API, whose read-scope on this bot token
    is unverified."""
    uk_event = next((e for e in event_rows if e is not None and e["source"] == "uk"), None)
    if uk_event is None:
        return "no uk (UptimeKuma) member in this cluster — nothing to match a push line against"
    wp = _wp_module()
    if wp is None:
        return "watchdog-poll.py sibling module did not load — cannot fetch #alerts"
    token = wp.resolve_secret("HOMELAB_API_KEY")
    if not token:
        return "HOMELAB_API_KEY unresolved — cannot fetch #alerts history"
    monitor_key = normalize_title(uk_event["title"] or "")
    msgs, _latest, ok = wp.poll_slack_messages({"HOMELAB_API_KEY": token}, ALERTS_CHANNEL, None,
                                                skip_uk_push=False)
    if not ok:
        return "#alerts fetch failed (see watchdog-poll.py's own poll_slack_messages)"
    matches = []
    for m in msgs:
        text = (m.get("payload") or {}).get("text") or m.get("title") or ""
        bm = _BRACKET_PREFIX_RE.match(text.strip())
        if bm and normalize_title(bm.group(1)) == monitor_key:
            matches.append((m.get("external_id") or "0", text))
    if not matches:
        return f"no `[{uk_event['title']}] ...` message found in the last {len(msgs)} #alerts messages"
    matches.sort(key=lambda t: t[0])
    return matches[-1][1]


_EVIDENCE_GATHERERS = {
    "meteo-health": _gather_meteo_health,
    "gateway-starts": _gather_gateway_starts,
    "hermes-log-tail": _gather_hermes_log_tail,
    "kuma-push-last": _gather_kuma_push_last,
}
assert set(_EVIDENCE_GATHERERS) == set(EVIDENCE_ALLOWLIST), "EVIDENCE_ALLOWLIST and its gatherers drifted"

EVIDENCE_BLOCK_HEADER = (
    "CAPTURED RUNTIME STATE — gathered by the triage loop from the live machine just "
    "before this brief was built. This is NOT visible from the repo checkout the episode "
    "runs in, and the episode CANNOT re-run these commands itself; treat it as "
    "authoritative for what it reports, but it may be incomplete (see any per-key error "
    "below) or already stale by the time it's read."
)


def _gather_evidence(key: str, event_rows: list[sqlite3.Row]) -> str:
    fn = _EVIDENCE_GATHERERS.get(key)
    if fn is None:
        return f"unknown evidence key {key!r} (policy/code drifted after load_policy() validated it)"
    ok, result = _run_bounded(fn, event_rows)
    return result if ok else f"evidence command {key!r} failed: {result}"


def _evidence_keys_for_members(members: list[sqlite3.Row], event_rows_by_id: dict[int, sqlite3.Row],
                                policy: dict[str, Any]) -> list[str]:
    """Re-derives which policy rule matched each member — triage_items only
    stores the resolved `repo`, never which rule produced it — and unions
    their declared `evidence` lists, in first-member-seen order. A cluster's
    evidence set is whatever its own member signatures' rules ask for."""
    keys: list[str] = []
    for m in members:
        er = event_rows_by_id.get(m["event_id"])
        if er is None:
            continue
        rule = _match_rule(_match_targets(er), policy["rules"])
        if rule is None:
            continue
        for key in rule.get("evidence") or []:
            if key not in keys:
                keys.append(key)
    return keys


def _build_evidence_block(keys: list[str], event_rows_by_id: dict[int, sqlite3.Row], max_chars: int) -> str:
    """Renders every requested key's output into one labelled block, each
    capped at EVIDENCE_CAP_CHARS, the whole block additionally capped at
    `max_chars` — the REMAINING budget in the brief the caller computed, so
    evidence is what gets truncated when a brief is tight, never the brief's
    own structure (the alert list, the sibling items, the closing
    instructions) around it."""
    if not keys or max_chars <= 0:
        return ""
    event_rows = list(event_rows_by_id.values())
    parts = []
    for key in keys:
        text = _cap_evidence(_gather_evidence(key, event_rows), EVIDENCE_CAP_CHARS)
        parts.append(f"--- {key} ---\n{text}")
    block = EVIDENCE_BLOCK_HEADER + "\n" + "\n".join(parts)
    cap = min(max_chars, EVIDENCE_TOTAL_CAP_CHARS)
    if len(block) > cap:
        truncation_note = "\n…(evidence truncated to fit the brief cap)"
        keep = max(cap - len(truncation_note), 0)
        block = block[:keep].rstrip() + truncation_note
    return block


def _build_cluster_brief(*, repo: str, members: list[sqlite3.Row], event_rows_by_id: dict[int, sqlite3.Row],
                          sibling_events: list[dict[str, str]], evidence_keys: list[str] | None = None) -> str:
    lines = [f"Repo: {repo}"]
    if len(members) == 1:
        lines.append("Alert:")
    else:
        lines.append(f"{len(members)} alert signatures fired together and MAY share one root cause:")
    for m in members:
        er = event_rows_by_id[m["event_id"]]
        lines.append(f"- `{m['signature']}` — {m['occurrences']}x since {_fmt_ts(m['first_seen'])} "
                      f"(last {_fmt_ts(m['last_seen'])}) — {er['title']}")
        for t in _recent_raw_texts(er)[:2]:
            lines.append(f"    raw: {t}")
        if m["artifact_url"]:
            lines.append(f"    already-linked artifact from a prior investigation of this EXACT "
                          f"signature: {m['artifact_url']} — check whether it already fixes this "
                          f"(including whether it simply hasn't been merged yet) before proposing "
                          f"something new")
    if sibling_events:
        lines.append(f"Other open triage items in {repo}:")
        lines.extend(f"- {s['signature']}: {s['title']}" for s in sibling_events)

    closing_lines = [""]
    if len(members) > 1:
        closing_lines.append(
            "Determine whether these signatures share a single root cause before proposing separate "
            "fixes. This grouping is a HYPOTHESIS from deterministic co-occurrence, never an "
            "assertion — confirm or split it. If they do NOT share a root cause, say so explicitly "
            f"in your summary or recommendation using the exact phrase '{DISSOLVE_MARKER}' so they "
            "can be re-triaged individually."
        )
    closing_lines.append(
        "This alert reached the auto-triage escalation threshold (repeat occurrences or stayed open "
        "long enough). Investigate the root cause and report a verdict. No LLM was involved in "
        "reaching this point — deduplication, clustering and escalation are all deterministic."
    )

    # Evidence is built LAST, sized against whatever budget the rest of the
    # brief (which must never itself be truncated) leaves behind — see
    # _build_evidence_block()'s own docstring and the module docstring's
    # DRY-RUN/brief-cap contract.
    rest = "\n".join(lines + closing_lines)
    evidence_block = ""
    if evidence_keys:
        remaining = MAX_BRIEF_CHARS - len(rest) - 2  # 2 for the blank-line join below
        evidence_block = _build_evidence_block(evidence_keys, event_rows_by_id, max(remaining, 0))

    if evidence_block:
        full = "\n".join(lines) + "\n\n" + evidence_block + "\n" + "\n".join(closing_lines)
    else:
        full = rest
    return _cap_brief(full)


def _run_hermes_cc_dispatch(*, repo: str, brief: str, event_id: int, channel: str | None,
                             thread_ts: str | None, timeout: int) -> dict[str, Any] | None:
    """Shell out to hermes-cc.sh's `dispatch` verb. THE BRIEF NEVER TOUCHES
    ARGV — it goes on stdin, exactly the invariant hermes-cc.sh's own header
    documents and enforces. `event_id` is the cluster's PRIMARY member —
    `--origin-event` takes exactly one events.id (one dispatches row = one
    episode); the caller writes events.dispatch_id on every OTHER member
    itself afterward (see escalate_cluster()). Returns the parsed --json
    object on a clean `ok: true` response, None on anything else (never
    raises)."""
    argv = [str(HERMES_CC_BIN), "dispatch", repo, "--tier", "investigate", "--json",
            "--origin-event", str(event_id)]
    if channel:
        argv += ["--origin-channel", channel]
        if thread_ts:
            argv += ["--origin-thread", thread_ts]
    try:
        r = subprocess.run(argv, input=brief, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"triage: hermes-cc.sh dispatch failed to run for {repo}: {e}", file=sys.stderr)
        return None
    if r.returncode != 0:
        print(f"triage: hermes-cc.sh dispatch exited {r.returncode} for {repo}: "
              f"{r.stderr.strip()[:500]}", file=sys.stderr)
        return None
    try:
        obj = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"triage: hermes-cc.sh dispatch returned non-JSON for {repo}: {r.stdout[:300]}", file=sys.stderr)
        return None
    if not obj.get("ok") or not obj.get("jobId"):
        print(f"triage: hermes-cc.sh dispatch not ok for {repo}: {obj}", file=sys.stderr)
        return None
    return obj


def _is_escalation_eligible(item: sqlite3.Row, policy: dict[str, Any], now: dt.datetime) -> bool:
    if item["occurrences"] >= policy["minOccurrences"]:
        return True
    return _age_minutes(item["first_seen"], now) >= policy["minOpenMinutes"]


def _cooldown_ok(conn: sqlite3.Connection, item: sqlite3.Row, policy: dict[str, Any],
                  now: dt.datetime) -> bool:
    """No prior dispatch for this signature -> always ok. Otherwise wait out
    cooldownHours from the PRIOR dispatch's created_at before re-escalating a
    signature that recurred — a flapping alert should not open a fresh
    investigate episode every 10 minutes."""
    if not item["dispatch_job"]:
        return True
    row = conn.execute("SELECT created_at FROM dispatches WHERE job_id=?", (item["dispatch_job"],)).fetchone()
    created = _parse_ts(row["created_at"]) if row else None
    if created is None:
        return True
    return (now - created).total_seconds() >= policy["cooldownHours"] * 3600


def escalate_cluster(conn: sqlite3.Connection, repo: str, members: list[sqlite3.Row], now: dt.datetime,
                      policy: dict[str, Any], *, dry_run: bool) -> str | None:
    sigs = [m["signature"] for m in members]
    if dry_run:
        print(f"[dry-run] would dispatch investigate for cluster in {repo}: {sigs}")
        card_channel = _card_channel(policy)
        print(f"[dry-run] would post card for cluster in {repo} ({len(members)} signature"
              f"{'s' if len(members) != 1 else ''}: {sigs}) in {card_channel}")
        return None

    event_rows_by_id = {m["event_id"]: _get_event(conn, m["event_id"]) for m in members}
    exclude_ids = [m["event_id"] for m in members]
    sibling_events = _sibling_open_items(conn, repo, exclude_ids)
    evidence_keys = _evidence_keys_for_members(members, event_rows_by_id, policy)
    brief = _build_cluster_brief(repo=repo, members=members, event_rows_by_id=event_rows_by_id,
                                  sibling_events=sibling_events, evidence_keys=evidence_keys)
    primary = members[0]
    channel = _card_channel(policy)
    result = _run_hermes_cc_dispatch(
        repo=repo, brief=brief, event_id=primary["event_id"], channel=channel, thread_ts=None,
        timeout=SUBPROCESS_TIMEOUT,
    )
    if result is None:
        return None
    job_id = result["jobId"]
    now_iso = _now_iso(now)
    for m in members:
        conn.execute(
            "UPDATE triage_items SET state=?, dispatch_job=?, updated_at=? WHERE event_id=?",
            (STATE_INVESTIGATING, job_id, now_iso, m["event_id"]),
        )
    dispatch_row = conn.execute("SELECT id FROM dispatches WHERE job_id=?", (job_id,)).fetchone()
    if dispatch_row is not None:
        for m in members:
            conn.execute("UPDATE events SET dispatch_id=? WHERE id=?", (dispatch_row["id"], m["event_id"]))
    else:
        print(f"triage: hermes-cc.sh reported job {job_id} but no matching dispatches row was found "
              f"(events.dispatch_id left unset for {sigs})", file=sys.stderr)
    conn.commit()

    # The card only starts existing now (state just became `investigating`,
    # the first CARDED_STATES member of this cluster) — post it immediately,
    # then retro-fill origin_thread_ts on the dispatches row so
    # dispatch-sweep.py's actionable-dispatch nudge lands on the card's own
    # thread. Same "small follow-up write to a column dispatch-sweep.py
    # doesn't own" pattern that file already uses for status/verdict_json/
    # artifact_url/merged_at/poll_misses/reported_at on this same table.
    fresh_members = [_get_item(conn, m["event_id"]) for m in members]
    fresh_members = [m for m in fresh_members if m is not None]
    fresh_events = [event_rows_by_id[m["event_id"]] for m in fresh_members]
    fresh_members = sync_card(conn, fresh_members, fresh_events, policy, dry_run=False)
    card_ts = fresh_members[0]["card_ts"] if fresh_members else None
    if card_ts:
        conn.execute("UPDATE dispatches SET origin_thread_ts=? WHERE job_id=?", (card_ts, job_id))
        conn.commit()
    return job_id


def escalate(conn: sqlite3.Connection, policy: dict[str, Any], now: dt.datetime, *, dry_run: bool) -> None:
    """Groups every eligible `new`+mapped item BY REPO and opens at most one
    sideclaw dispatch per repo per run (a cluster — see module docstring),
    capped at MAX_CLUSTER_SIGNATURES members per brief. Concurrency and daily
    budget are checked once per run, decremented as clusters are opened, so
    later repos in the same run correctly see an exhausted cap."""
    denied = _denied_repos()
    open_investigations = _count_open_investigation_clusters(conn)
    budget_used_today = _investigate_dispatches_today(conn, now)

    candidates = conn.execute(
        "SELECT * FROM triage_items WHERE state=? AND repo IS NOT NULL ORDER BY event_id", (STATE_NEW,)
    ).fetchall()
    by_repo: dict[str, list[sqlite3.Row]] = {}
    for item in candidates:
        if item["snoozed_until"]:
            continue
        repo = item["repo"]
        if repo in denied:
            print(f"triage: repo {repo!r} for {item['signature']} is denied in dispatch-repos.json "
                  f"— fix the policy rule, this will never escalate", file=sys.stderr)
            continue
        if not _is_escalation_eligible(item, policy, now):
            continue
        if not _cooldown_ok(conn, item, policy, now):
            print(f"triage: {item['signature']} recurred inside cooldownHours, not re-escalating yet",
                  file=sys.stderr)
            continue
        by_repo.setdefault(repo, []).append(item)

    for repo, members in by_repo.items():
        if open_investigations >= MAX_OPEN_INVESTIGATIONS:
            print(f"triage: at MAX_OPEN_INVESTIGATIONS={MAX_OPEN_INVESTIGATIONS}, deferring cluster in "
                  f"{repo} ({[m['signature'] for m in members]})", file=sys.stderr)
            continue
        if budget_used_today >= DAILY_INVESTIGATE_BUDGET:
            print(f"triage: at DAILY_INVESTIGATE_BUDGET={DAILY_INVESTIGATE_BUDGET}, deferring cluster "
                  f"in {repo}", file=sys.stderr)
            continue
        group = members[:MAX_CLUSTER_SIGNATURES]
        overflow = members[MAX_CLUSTER_SIGNATURES:]
        if overflow:
            print(f"triage: {len(overflow)} more eligible {repo} items wait for next run "
                  f"(cluster cap {MAX_CLUSTER_SIGNATURES}/brief): {[m['signature'] for m in overflow]}",
                  file=sys.stderr)
        job_id = escalate_cluster(conn, repo, group, now, policy, dry_run=dry_run)
        # escalate_cluster() always returns None under --dry-run (it never
        # calls hermes-cc.sh) — `or dry_run` keeps the two caps' PREVIEW
        # meaningful across multiple repos in one dry-run pass (a later repo
        # in the same run correctly sees an exhausted cap), without ever
        # persisting anything. A REAL run only counts an actual success, so a
        # failed dispatch is retried next run rather than burning budget.
        if job_id or dry_run:
            open_investigations += 1
            budget_used_today += 1


# --- verb outcomes — a deterministic local probe, never an episode -----------

def _run_verb(argv: list[str], *, timeout: int) -> dict[str, Any] | None:
    """Run one VERB_ALLOWLIST-resolved argv, parse its --json stdout. Never
    raises — a spawn failure, timeout, non-zero exit, or unparseable stdout
    all fold into a small dict with an `_error` key so the caller can render
    something on the card either way, rather than the row silently getting
    stuck."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return {"_error": str(e)}
    try:
        obj = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"_error": f"non-JSON output (rc={r.returncode}): {r.stdout.strip()[:300] or '(empty)'}"}
    if r.returncode not in (0, 3):
        # hermes-ops.sh's own convention: env-check exits 3 for "ok: false",
        # which is a normal, expected outcome here (that IS the dangling ref
        # this verb exists to surface) — only something else is a real error.
        return {"_error": f"unexpected exit {r.returncode}: {json.dumps(obj)[:300]}"}
    return obj if isinstance(obj, dict) else {"_error": f"non-object JSON: {r.stdout[:300]}"}


def _render_env_check_note(output: dict[str, Any] | None) -> str:
    """Deterministic prose for the needs_human card — no LLM, straight from
    hermes-ops.sh's own --json shape: {"ok", "homelab": {"danglingItems": [...],
    ...}, "vps": {...}}. The dangling item name and the exact remediation are
    inlined so the card is the whole answer — no further investigation should
    be needed."""
    if output is None or "_error" in output:
        err = (output or {}).get("_error", "no output")
        return f"env-check probe failed to run: {err}. Retry manually: `hermes-ops.sh env-check`."
    dangling: list[str] = []
    for host_key in ("homelab", "vps"):
        host = output.get(host_key)
        if isinstance(host, dict):
            for item in host.get("danglingItems") or []:
                dangling.append(f"{host_key}: `{item}`")
    if not dangling:
        return ("env-check ran and found no dangling item on this pass — likely transient; the "
                "underlying event will disappearance-resolve on its own if it clears.")
    items_text = "; ".join(dangling)
    return (
        f"Dangling 1Password item(s) — {items_text}. `op run` fails WHOLESALE on the shared "
        f".env.tpl until this is fixed, taking every cron sharing that template down at once. "
        f"Fix: restore/rename the item in 1Password, then run `make secrets-seed` (biometric "
        f"1Password prompt — MacBook only, this cannot be done headlessly on the mini)."
    )


def run_verbs(conn: sqlite3.Connection, policy: dict[str, Any], now: dt.datetime, *, dry_run: bool) -> None:
    """Every `new` item routed to a `verb` (never a `repo` — see classify())
    runs its allowlisted local command once eligibility is met, same
    minOccurrences/minOpenMinutes gate as an episode escalation. No
    concurrency/daily-budget cap: a verb is a bounded local probe, not a
    sideclaw episode, and doesn't compete for that budget. No cooldown
    tracking either — a verb-routed item runs at most ONCE, because its
    terminal state (`needs_human`) falls out of STATE_NEW candidates
    permanently; if the underlying condition later clears, the normal
    resolve path (events.resolved_at) closes it out without needing a
    re-run, and if it recurs after a reopen, running the probe again is
    exactly correct."""
    candidates = conn.execute(
        "SELECT * FROM triage_items WHERE state=? AND verb IS NOT NULL AND repo IS NULL ORDER BY event_id",
        (STATE_NEW,),
    ).fetchall()
    for item in candidates:
        if item["snoozed_until"]:
            continue
        if not _is_escalation_eligible(item, policy, now):
            continue
        verb = item["verb"]
        argv = VERB_ALLOWLIST.get(verb)
        if argv is None:
            print(f"triage: verb {verb!r} for {item['signature']} is not in VERB_ALLOWLIST — "
                  f"skipping (policy/code drifted after load_policy() validated it)", file=sys.stderr)
            continue
        if dry_run:
            print(f"[dry-run] would run verb {verb!r} for {item['signature']}")
            continue
        output = _run_verb(argv, timeout=VERB_TIMEOUT)
        note = _render_env_check_note(output) if verb == "env-check" else json.dumps(output)[:SECTION_TEXT_MAX]
        now_iso = _now_iso(now)
        conn.execute(
            "UPDATE triage_items SET state=?, note=?, updated_at=? WHERE event_id=?",
            (STATE_NEEDS_HUMAN, note, now_iso, item["event_id"]),
        )
        conn.commit()
        fresh_item = _get_item(conn, item["event_id"])
        event_row = _get_event(conn, item["event_id"])
        if fresh_item is not None and event_row is not None:
            sync_card(conn, [fresh_item], [event_row], policy, dry_run=False)


# --- dissolve — a cluster the episode itself says is unrelated ----------------

def _dissolve_cluster(conn: sqlite3.Connection, members: list[sqlite3.Row], now: dt.datetime,
                       *, dry_run: bool) -> None:
    """Reset every member to `new` so each re-escalates individually.
    `dispatch_job` is deliberately LEFT SET (only card_channel/card_ts/
    card_hash are cleared) — a `new` row is never grouped by
    `_cluster_groups()` (which only looks at CARDED_STATES), so the cluster
    is functionally gone for card/escalation purposes, but keeping the
    pointer means `_cooldown_ok()` still finds the dissolved dispatch's
    created_at and enforces a real cooldownHours wait. Without this, the very
    same `run()` that dissolves a cluster would see both members freshly
    eligible with no cooldown at all and instantly re-fuse them into an
    identical cluster in the escalate() call that follows — dissolve would be
    a no-op in practice. The tradeoff: a dissolved pair COULD re-cluster again
    after cooldownHours if both are still open — accepted, since a hard
    permanent split needs a negative-relationship table this schema doesn't
    have, and the split verdict stays visible in dispatches.verdict_json for
    whoever reads the history."""
    sigs = [m["signature"] for m in members]
    job_id = members[0]["dispatch_job"]
    if dry_run:
        print(f"[dry-run] would dissolve cluster {job_id}: {sigs}")
        return
    card_channel = members[0]["card_channel"]
    card_ts = members[0]["card_ts"]
    if card_channel and card_ts:
        token = resolve_slack_token()
        if token:
            sig_list = ", ".join(f"`{s}`" for s in sigs)
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": ":arrows_counterclockwise: Cluster split"}},
                {"type": "section", "text": {"type": "mrkdwn", "text":
                    f"The investigation found these did not share a root cause: {sig_list}. "
                    f"Each will be re-evaluated individually."}},
            ]
            update_blocks(card_channel, card_ts, blocks, "Cluster split — re-evaluating individually", token)
    now_iso = _now_iso(now)
    for m in members:
        conn.execute(
            "UPDATE triage_items SET state=?, card_channel=NULL, card_ts=NULL, "
            "card_hash=NULL, updated_at=? WHERE event_id=?",
            (STATE_NEW, now_iso, m["event_id"]),
        )
    conn.commit()


def maybe_dissolve_clusters(conn: sqlite3.Connection, now: dt.datetime, *, dry_run: bool) -> None:
    """A cluster (>1 member sharing one dispatch_job) that landed in plain
    `verdict` (not needs_human/pr_open — those found something actionable,
    splitting doesn't apply) whose folded verdict text contains
    DISSOLVE_MARKER gets unwound: every member goes back to `new`, its
    dispatch_job/card pointers cleared, so each re-escalates independently on
    a later run. Runs once per pass, before escalate() — "the cluster is
    dissolved on the next run" per the design this implements."""
    rows = conn.execute(
        "SELECT dispatch_job, count(*) c FROM triage_items WHERE dispatch_job IS NOT NULL AND state=? "
        "GROUP BY dispatch_job HAVING c > 1",
        (STATE_VERDICT,),
    ).fetchall()
    for row in rows:
        job_id = row["dispatch_job"]
        d = conn.execute("SELECT verdict_json FROM dispatches WHERE job_id=?", (job_id,)).fetchone()
        if d is None:
            continue
        result = _safe_json(d["verdict_json"])
        text_blob = " ".join(str(result.get(k) or "") for k in ("summary", "verdict", "recommendation"))
        if DISSOLVE_MARKER not in text_blob:
            continue
        members = conn.execute(
            "SELECT * FROM triage_items WHERE dispatch_job=? ORDER BY event_id", (job_id,)
        ).fetchall()
        _dissolve_cluster(conn, list(members), now, dry_run=dry_run)


# --- card rendering ------------------------------------------------------------

def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_card_blocks(members: list[sqlite3.Row], event_rows: list[sqlite3.Row], conn: sqlite3.Connection
                        ) -> list[dict[str, Any]]:
    primary = members[0]
    state = primary["state"]
    emoji = STATE_EMOJI.get(state, ":question:")
    if len(members) > 1:
        title = f"{len(members)} related alerts in `{primary['repo']}`"
    else:
        title = _escape(event_rows[0]["title"] or primary["signature"])[:140]
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{emoji} {title}"[:150]}},
    ]

    member_lines = [
        f"• `{m['signature']}` — {m['occurrences']}× since {_fmt_ts(m['first_seen'])} · "
        f"last {_fmt_ts(m['last_seen'])}"
        for m in members
    ]
    ctx_text = "\n".join(member_lines)
    if primary["repo"]:
        ctx_text += f"\nrepo `{primary['repo']}`"
    elif primary["verb"]:
        ctx_text += f"\nverb `{primary['verb']}`"
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": ctx_text[:SECTION_TEXT_MAX]}})

    if state == STATE_INVESTIGATING and primary["dispatch_job"]:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Investigation running — job `{primary['dispatch_job'][:8]}`"}],
        })
    elif state in (STATE_VERDICT, STATE_NEEDS_HUMAN, STATE_PR_OPEN) and primary["dispatch_job"]:
        d = conn.execute("SELECT verdict_json FROM dispatches WHERE job_id=?", (primary["dispatch_job"],)).fetchone()
        result = _safe_json(d["verdict_json"]) if d and d["verdict_json"] else {}
        summary = (result.get("summary") or "").strip()
        confidence = result.get("confidence") or "?"
        text_lines = []
        if summary:
            text_lines.append(_escape(summary))
        text_lines.append(f"_confidence {confidence}_")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(text_lines)[:SECTION_TEXT_MAX]}})
        evidence = result.get("evidence")
        if isinstance(evidence, list) and evidence:
            ev_lines = []
            for e in evidence[:3]:
                if isinstance(e, dict):
                    ev_lines.append(f"- `{_escape(str(e.get('file') or '?'))}` — {_escape(str(e.get('detail') or ''))}")
                else:
                    ev_lines.append(f"- {_escape(str(e))}")
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(ev_lines)}})
        artifact_url = primary["artifact_url"]
        if artifact_url:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Artifact:* <{artifact_url}>"}})
        if state == STATE_NEEDS_HUMAN and primary["note"]:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"↳ _{_escape(primary['note'])}_"}]})
    elif state == STATE_NEEDS_HUMAN and primary["note"]:
        # A verb outcome (run_verbs()) — no dispatch_job at all, since no
        # sideclaw episode was ever opened. The note IS the whole verdict: a
        # deterministic local probe's output, not an episode's.
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _escape(primary["note"])[:SECTION_TEXT_MAX]}})
    elif state == STATE_SNOOZED:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Snoozed until {_fmt_ts(primary['snoozed_until'])}"}],
        })
    elif state == STATE_RESOLVED and (primary["note"] or "").startswith(
            (QUIET_RESOLVE_NOTE_PREFIX, RECOVERY_PAIRED_NOTE_PREFIX, LIVENESS_CONFIRMED_NOTE_PREFIX)):
        # Only ever rendered for the grouped-source resolve paths (see
        # resolve_quiet_grouped()/resolve_recovery_paired()) and the liveness
        # confirm path (maybe_check_liveness()) — an ordinary event-driven
        # resolve clears `note` outright (apply_resolutions()), so this never
        # fires for a genuine state-source (uk/docker/op_refs) recovery,
        # which needs no caveat.
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"↳ _{_escape(primary['note'])}_"}]})
    elif state == STATE_IMPLEMENTING and primary["implement_job"]:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Auto-implement running — job `{primary['implement_job'][:8]}`"}],
        })
    elif state == STATE_VALIDATING:
        text = "Independent validation running"
        if primary["validation_job"]:
            text += f" — job `{primary['validation_job'][:8]}`"
        if primary["pr_url"]:
            text += f"\nPull request: <{primary['pr_url']}>"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text[:SECTION_TEXT_MAX]}})
    elif state == STATE_MERGE_BLOCKED:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                        "text": _escape(primary["note"] or "blocked, no further detail")[:SECTION_TEXT_MAX]}})
    elif state == STATE_MERGED:
        text = f"Merged: <{primary['pr_url']}>" if primary["pr_url"] else "Merged"
        if primary["note"]:
            text += f"\n_{_escape(primary['note'])}_"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text[:SECTION_TEXT_MAX]}})
    elif state == STATE_LIVENESS_PENDING:
        text = f"Deployed — confirming liveness by {_fmt_ts(primary['liveness_deadline'])}"
        if primary["pr_url"]:
            text += f"\nPull request: <{primary['pr_url']}>"
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": text}]})

    footer_sig = primary["signature"] if len(members) == 1 else f"<signature> ({len(members)} in this cluster)"
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"Snooze one member: `triage.py --snooze {footer_sig} --hours 24`"}],
    })
    return blocks


def _card_hash(blocks: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(blocks, sort_keys=True).encode()).hexdigest()


def sync_card(conn: sqlite3.Connection, members: list[sqlite3.Row], event_rows: list[sqlite3.Row],
              policy: dict[str, Any], *, dry_run: bool) -> list[sqlite3.Row]:
    """Render this cluster's card and post/update Slack ONLY if the rendered
    content changed since the last sync (the card_hash short-circuit — the
    property that keeps the channel from becoming a firehose again). Every
    member row carries an identical copy of card_channel/card_ts/card_hash
    (rather than one "owning" row) so cluster membership stays self-
    describing even after a process restart. Returns the (possibly reloaded)
    member rows.

    A `resolved` cluster with no `card_ts` was never carded in the first
    place — every one of the resolve paths (apply_resolutions(),
    resolve_quiet_grouped(), resolve_recovery_paired()) can flip an
    unescalated `new` row straight to `resolved` on a quiet/disappeared
    signal, and a card announcing the resolution of a problem nobody was
    told about is exactly the noise this loop replaced (see CARDED_STATES's
    own comment for the incident). The fix is a `chat.postMessage` this
    branch must never make — an already-carded item still gets its final
    `chat.update` below, unchanged."""
    if not members:
        return members
    primary = members[0]
    if primary["state"] == STATE_RESOLVED and not primary["card_ts"]:
        return members
    blocks = render_card_blocks(members, event_rows, conn)
    new_hash = _card_hash(blocks)
    if new_hash == primary["card_hash"]:
        return members
    channel = primary["card_channel"] or _card_channel(policy)
    if len(members) > 1:
        fallback = f"{len(members)} related alerts in {primary['repo']}"
    else:
        fallback = (event_rows[0]["title"] or primary["signature"])[:150]
    if dry_run:
        action = "update" if primary["card_ts"] else "post"
        sigs = [m["signature"] for m in members]
        print(f"[dry-run] would {action} card for {sigs} (state={primary['state']}) in {channel}")
        return members
    token = resolve_slack_token()
    if not token:
        print(f"triage: no Slack token, cannot sync card for cluster "
              f"{[m['signature'] for m in members]}", file=sys.stderr)
        return members
    if primary["card_ts"]:
        ok, ts = update_blocks(channel, primary["card_ts"], blocks, fallback, token)
    else:
        ok, ts = post_blocks(channel, blocks, fallback, token)
    if not ok:
        print(f"triage: slack card sync failed for cluster {[m['signature'] for m in members]}", file=sys.stderr)
        return members
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    ts_value = ts or primary["card_ts"]
    for m in members:
        conn.execute(
            "UPDATE triage_items SET card_channel=?, card_ts=?, card_hash=?, updated_at=? WHERE event_id=?",
            (channel, ts_value, new_hash, now_iso, m["event_id"]),
        )
    conn.commit()
    return [r for r in (_get_item(conn, m["event_id"]) for m in members) if r is not None]


def fold_dispatch_verdict(conn: sqlite3.Connection, *, origin_event_id: int, job_id: str,
                           now: dt.datetime, dry_run: bool) -> None:
    """Called by dispatch-sweep.py once a dispatch tied to a triage cluster
    (dispatches.origin_event_id) reaches a terminal status. Looks up EVERY
    triage_items row sharing this `dispatch_job` (not just origin_event_id's
    own row — a cluster can have several), folds the verdict onto all of
    them, and syncs the shared card immediately rather than waiting for this
    file's own next 10-minute pass. Idempotent and safe to call on every
    sweep for a row already folded — the card_hash short-circuit makes a
    repeat call a no-op. `origin_event_id` is used only as a sanity check
    (the primary member should be among the rows found by job_id); job_id is
    authoritative for cluster membership."""
    members = conn.execute(
        "SELECT * FROM triage_items WHERE dispatch_job=? ORDER BY event_id", (job_id,)
    ).fetchall()
    if not members:
        return
    if origin_event_id not in {m["event_id"] for m in members}:
        print(f"triage: fold_dispatch_verdict: origin_event_id {origin_event_id} not among the "
              f"{len(members)} rows sharing dispatch_job {job_id} — proceeding on job_id anyway",
              file=sys.stderr)
    d = conn.execute(
        "SELECT status, verdict_json, artifact_url FROM dispatches WHERE job_id=?", (job_id,)
    ).fetchone()
    if d is None:
        return
    result = _safe_json(d["verdict_json"]) if d["verdict_json"] else {}
    next_action = (result.get("nextAction") or "").strip().lower()
    if d["artifact_url"]:
        new_state = STATE_PR_OPEN
    elif next_action == "human":
        new_state = STATE_NEEDS_HUMAN
    else:
        new_state = STATE_VERDICT
    blocker = ""
    if new_state == STATE_NEEDS_HUMAN:
        blocker = (result.get("recommendation") or result.get("summary") or "").strip()

    if dry_run:
        print(f"[dry-run] would fold dispatch {job_id} onto {len(members)} triage item(s): state={new_state}")
        return

    now_iso = _now_iso(now)
    for m in members:
        conn.execute(
            "UPDATE triage_items SET state=?, artifact_url=COALESCE(?, artifact_url), note=?, updated_at=? "
            "WHERE event_id=?",
            (new_state, d["artifact_url"], blocker or None, now_iso, m["event_id"]),
        )
    conn.commit()

    fresh_members = [r for r in (_get_item(conn, m["event_id"]) for m in members) if r is not None]
    fresh_events = [e for e in (_get_event(conn, m["event_id"]) for m in fresh_members) if e is not None]
    if fresh_members and len(fresh_members) == len(fresh_events):
        policy = load_policy()
        sync_card(conn, fresh_members, fresh_events, policy, dry_run=False)


# --- the auto-implement chain: verdict -> implement -> validate -> merge ----
# --- -> deploy -> verify (steps 6-10) -----------------------------------------
#
# Everything below is downstream of a STATE_VERDICT item whose folded
# investigate verdict already said nextAction=implement at confidence=high.
# Every step shells out to hermes-cc.sh (never sideclaw directly — that
# script is "the ONLY way the Hermes agent opens a Claude Code episode", per
# its own header) and re-derives what it needs from watchdog.db every run,
# same as the rest of this file. No LLM call happens IN THIS FILE at any of
# these steps either — the dispatched episodes run one each, which is
# inherent to what "investigate"/"implement" mean, not something this loop
# does itself.

def _hermes_cc_status(job_id: str) -> dict[str, Any] | None:
    """`hermes-cc.sh status <job-id> --json` — a single poll, never --wait
    (an implement episode can run 30 minutes; this loop is a 10-minute cron
    and must never block inside it). Returns the parsed --json object, or
    None on anything that could not even be read (never raises)."""
    argv = [str(HERMES_CC_BIN), "status", job_id, "--json"]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"triage: hermes-cc.sh status failed for {job_id}: {e}", file=sys.stderr)
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"triage: hermes-cc.sh status returned non-JSON for {job_id}: {r.stdout[:300]}", file=sys.stderr)
        return None


def _run_hermes_cc_auto_implement(*, repo: str, event_id: int) -> str | None:
    """Step 6 — `dispatch <repo> --tier implement --auto-from-item <event_id>`.
    hermes-cc.sh re-checks every precondition itself from watchdog.db (see
    its own require_auto_from_item()); this function only decides WHICH item
    is a candidate (maybe_auto_implement()) and shells out. The brief is
    deliberately terse — the analysis already happened in the linked
    investigate episode, which the implement episode can and should re-read
    itself inside the repo (CLAUDE.md, the actual code) rather than trusting
    a second-hand summary here."""
    brief = (
        "A prior read-only investigation of this repo (dispatched by the alert triage loop) "
        "already concluded, at high confidence, that the fix should be implemented — re-read "
        "that investigation's own verdict and evidence yourself (it ran against this exact "
        "repo) before writing anything, then implement the fix it described. If what you find "
        "on re-reading no longer supports that conclusion, say so in your own verdict and stop "
        "rather than forcing a change."
    )
    argv = [str(HERMES_CC_BIN), "dispatch", repo, "--tier", "implement",
            "--auto-from-item", str(event_id), "--origin-event", str(event_id),
            "--why", "triage auto-implement: investigation concluded implement at high confidence",
            "--json"]
    try:
        r = subprocess.run(argv, input=brief, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"triage: hermes-cc.sh auto-implement failed to run for {repo}: {e}", file=sys.stderr)
        return None
    if r.returncode != 0:
        print(f"triage: hermes-cc.sh auto-implement exited {r.returncode} for {repo}: "
              f"{r.stderr.strip()[:500]}", file=sys.stderr)
        return None
    try:
        obj = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"triage: hermes-cc.sh auto-implement returned non-JSON for {repo}: {r.stdout[:300]}",
              file=sys.stderr)
        return None
    if not obj.get("ok") or not obj.get("jobId"):
        print(f"triage: hermes-cc.sh auto-implement not ok for {repo}: {obj}", file=sys.stderr)
        return None
    return obj["jobId"]


def maybe_auto_implement(conn: sqlite3.Connection, policy: dict[str, Any], now: dt.datetime,
                          *, dry_run: bool) -> None:
    """Step 6. A STATE_VERDICT item is eligible once, the moment its folded
    investigate verdict (dispatches.verdict_json, keyed by its own
    dispatch_job) reads nextAction=implement at confidence=high AND it has
    not already been auto-implemented (implement_job IS NULL) — the same
    "runs at most once" shape run_verbs() already uses, for the same reason:
    the outcome falls out of the state machine (a re-triggered item is no
    longer in STATE_VERDICT once this fires)."""
    candidates = conn.execute(
        "SELECT * FROM triage_items WHERE state=? AND dispatch_job IS NOT NULL AND implement_job IS NULL "
        "ORDER BY event_id", (STATE_VERDICT,)
    ).fetchall()
    for item in candidates:
        if item["repo"] is None:
            continue
        d = conn.execute("SELECT verdict_json FROM dispatches WHERE job_id=?", (item["dispatch_job"],)).fetchone()
        if d is None:
            continue
        verdict = _safe_json(d["verdict_json"])
        if (verdict.get("nextAction") or "").strip().lower() != "implement":
            continue
        if (verdict.get("confidence") or "").strip().lower() != "high":
            continue
        if dry_run:
            print(f"[dry-run] would auto-implement {item['signature']} in {item['repo']} "
                  f"(event {item['event_id']})")
            continue
        # CLAIM BEFORE DISPATCH, not after. The eligibility query above is
        # `state='verdict' AND implement_job IS NULL`, so recording the claim only
        # after hermes-cc.sh returns leaves a window: if this process dies between
        # the dispatch and the UPDATE, the item is still eligible on the next tick
        # and a SECOND implement episode opens for the same verdict — duplicate
        # branches and duplicate draft PRs, bounded only by the 5/day budget. The
        # conditional UPDATE is the claim: `AND state=?` makes it a compare-and-set,
        # so a concurrent run that already claimed this item changes 0 rows and this
        # one skips instead of racing it.
        now_iso = _now_iso(now)
        claimed = conn.execute(
            "UPDATE triage_items SET state=?, updated_at=? WHERE event_id=? AND state=? "
            "AND implement_job IS NULL",
            (STATE_IMPLEMENTING, now_iso, item["event_id"], STATE_VERDICT),
        ).rowcount
        conn.commit()
        if not claimed:
            continue
        job_id = _run_hermes_cc_auto_implement(repo=item["repo"], event_id=item["event_id"])
        if job_id is None:
            # Dispatch refused or failed, so nothing is running — hand the claim back
            # rather than stranding the item in `implementing` with no job to poll.
            conn.execute(
                "UPDATE triage_items SET state=?, updated_at=? WHERE event_id=? AND state=?",
                (STATE_VERDICT, _now_iso(now), item["event_id"], STATE_IMPLEMENTING),
            )
            conn.commit()
            continue
        conn.execute(
            "UPDATE triage_items SET implement_job=?, updated_at=? WHERE event_id=?",
            (job_id, _now_iso(now), item["event_id"]),
        )
        conn.commit()
        fresh_item, fresh_event = _get_item(conn, item["event_id"]), _get_event(conn, item["event_id"])
        if fresh_item is not None and fresh_event is not None:
            sync_card(conn, [fresh_item], [fresh_event], policy, dry_run=False)


def _run_hermes_cc_validation(conn: sqlite3.Connection, *, repo: str, event_id: int,
                               implement_job: str, pr_url: str) -> str | None:
    """Step 7 — a SECOND investigate episode, on VALIDATION_MODEL (a
    deliberately DIFFERENT model from the one that wrote the implement
    episode), reviewing that pull request's actual diff against the repo:
    is the change correct, and does the PR body's own claims match the
    diff? This is not ceremony — in the incident that shipped this file, the
    implement episode asserted the wrong comparator semantics in its own PR
    body while the diff itself was right, and only a second, independent
    read caught it. Binds the validation job onto the IMPLEMENT dispatch's
    own row (dispatches.validation_job_id) the moment it opens — the
    'extra writer touching a column it doesn't own' pattern dispatch-sweep.py
    and escalate_cluster() already use on this same table — so cmd_merge's
    gate has something to read even before this validation finishes (NULL
    still correctly blocks a merge attempted too early)."""
    brief = (
        f"Review this pull request: {pr_url}\n\n"
        "Fetch its actual diff (e.g. `gh pr diff <number>`, or the branch's commits against "
        "the default branch — this worktree has the repo, use it) and read it against the "
        "repo's own code and CLAUDE.md. Answer two questions: (1) Is the change correct — "
        "does it do what it claims, with no obvious bug, and does it match this repo's own "
        "conventions? (2) Does the pull request's own title/body accurately describe what the "
        "diff actually does, or does it overstate/misstate it?\n\n"
        f"End your summary or recommendation with the EXACT phrase '{VALIDATION_CONFIRM_MARKER}' "
        f"if both answers are yes, or '{VALIDATION_DISAGREE_MARKER}' if either is not — always "
        "exactly one of the two, verbatim, on its own — this is read by a script, not a human."
    )
    argv = [str(HERMES_CC_BIN), "dispatch", repo, "--tier", "investigate",
            "--model", VALIDATION_MODEL, "--origin-event", str(event_id), "--json"]
    try:
        r = subprocess.run(argv, input=brief, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"triage: hermes-cc.sh validation dispatch failed for {repo}: {e}", file=sys.stderr)
        return None
    if r.returncode != 0:
        print(f"triage: hermes-cc.sh validation dispatch exited {r.returncode} for {repo}: "
              f"{r.stderr.strip()[:500]}", file=sys.stderr)
        return None
    try:
        obj = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"triage: hermes-cc.sh validation dispatch returned non-JSON for {repo}: {r.stdout[:300]}",
              file=sys.stderr)
        return None
    if not obj.get("ok") or not obj.get("jobId"):
        print(f"triage: hermes-cc.sh validation dispatch not ok for {repo}: {obj}", file=sys.stderr)
        return None
    job_id = obj["jobId"]
    conn.execute("UPDATE dispatches SET validation_job_id=? WHERE job_id=?", (job_id, implement_job))
    conn.commit()
    return job_id


def _run_hermes_cc_merge(job_id: str) -> dict[str, Any] | None:
    """Step 8 — `merge <job-id> --confirm`. `merge`'s own `--confirm` is an
    ungated, instruction-level flag (unlike `dispatch --tier implement`,
    which needs the signed-approval OR --auto-from-item gate) — owner
    decision, see hermes-cc.sh's own header: confirming the implement WAS
    the approval, landing it is finishing the thing already said yes to.
    Every real bound (declared path scope, CI reality, this exact
    validation) is enforced INSIDE cmd_merge, re-checked against the
    current head — this call is not itself a trust boundary."""
    argv = [str(HERMES_CC_BIN), "merge", job_id, "--why",
            "triage auto-merge: step-7 validation confirmed", "--confirm", "--json"]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"triage: hermes-cc.sh merge failed to run for {job_id}: {e}", file=sys.stderr)
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"triage: hermes-cc.sh merge returned non-JSON for {job_id}: {r.stdout[:300]}", file=sys.stderr)
        return None


def poll_implement_jobs(conn: sqlite3.Connection, policy: dict[str, Any], now: dt.datetime,
                         *, dry_run: bool) -> None:
    """Step 6 -> 7. Polls every STATE_IMPLEMENTING item once. A terminal
    result carrying a pull request opens the step-7 validation episode; a
    terminal result with no artifact (failed, interrupted, or done with
    nothing to show) blocks the chain outright — STATE_MERGE_BLOCKED, never
    a silent drop, so the card says why nothing landed."""
    if dry_run:
        return
    items = conn.execute(
        "SELECT * FROM triage_items WHERE state=? AND implement_job IS NOT NULL", (STATE_IMPLEMENTING,)
    ).fetchall()
    for item in items:
        resp = _hermes_cc_status(item["implement_job"])
        if resp is None:
            continue
        status = resp.get("status")
        if status not in ("done", "failed", "interrupted", "lost"):
            continue
        now_iso = _now_iso(now)
        artifact_url = resp.get("artifactUrl")
        if status != "done" or not artifact_url:
            reason = resp.get("error") or ((resp.get("verdict") or {}).get("summary")) or "no further detail"
            note = f"implement episode {item['implement_job']} finished '{status}' with no pull request: {reason}"
            conn.execute(
                "UPDATE triage_items SET state=?, note=?, updated_at=? WHERE event_id=?",
                (STATE_MERGE_BLOCKED, note, now_iso, item["event_id"]),
            )
        else:
            val_job = _run_hermes_cc_validation(conn, repo=item["repo"], event_id=item["event_id"],
                                                 implement_job=item["implement_job"], pr_url=artifact_url)
            if val_job is None:
                conn.execute(
                    "UPDATE triage_items SET state=?, note=?, pr_url=?, updated_at=? WHERE event_id=?",
                    (STATE_MERGE_BLOCKED, "could not open the step-7 validation episode", artifact_url,
                     now_iso, item["event_id"]),
                )
            else:
                conn.execute(
                    "UPDATE triage_items SET state=?, validation_job=?, pr_url=?, updated_at=? WHERE event_id=?",
                    (STATE_VALIDATING, val_job, artifact_url, now_iso, item["event_id"]),
                )
        conn.commit()
        fresh_item, fresh_event = _get_item(conn, item["event_id"]), _get_event(conn, item["event_id"])
        if fresh_item is not None and fresh_event is not None:
            sync_card(conn, [fresh_item], [fresh_event], policy, dry_run=False)


def poll_validation_jobs(conn: sqlite3.Connection, policy: dict[str, Any], now: dt.datetime,
                          *, dry_run: bool) -> None:
    """Step 7 -> 8. Polls every STATE_VALIDATING item once. A DISAGREEING,
    FAILED, or ERRORED validation blocks the merge outright — never read as
    a pass (the brief's own words). Only an explicit CONFIRMED marker with
    no DISAGREE marker in the same text calls `merge`; its own outcome
    (landed, or refused by cmd_merge's gate) decides the next state."""
    if dry_run:
        return
    items = conn.execute(
        "SELECT * FROM triage_items WHERE state=? AND validation_job IS NOT NULL", (STATE_VALIDATING,)
    ).fetchall()
    for item in items:
        resp = _hermes_cc_status(item["validation_job"])
        if resp is None:
            continue
        status = resp.get("status")
        if status not in ("done", "failed", "interrupted", "lost"):
            continue
        verdict = resp.get("verdict") or {}
        text_blob = " ".join(str(verdict.get(k) or "") for k in ("summary", "verdict", "recommendation"))
        confirmed = (status == "done" and VALIDATION_CONFIRM_MARKER in text_blob
                     and VALIDATION_DISAGREE_MARKER not in text_blob)
        outcome = "confirmed" if confirmed else ("disagreed" if status == "done" else "error")
        conn.execute("UPDATE dispatches SET validation_status=? WHERE job_id=?",
                     (outcome, item["implement_job"]))
        conn.commit()
        now_iso = _now_iso(now)
        if outcome != "confirmed":
            note = (f"step-7 validation ({outcome}): "
                    f"{verdict.get('summary') or resp.get('error') or 'no further detail'}")
            conn.execute(
                "UPDATE triage_items SET state=?, note=?, updated_at=? WHERE event_id=?",
                (STATE_MERGE_BLOCKED, note, now_iso, item["event_id"]),
            )
            conn.commit()
        else:
            merge_result = _run_hermes_cc_merge(item["implement_job"])
            if merge_result is None:
                conn.execute(
                    "UPDATE triage_items SET state=?, note=?, updated_at=? WHERE event_id=?",
                    (STATE_MERGE_BLOCKED, "validation confirmed but the merge call itself failed to run",
                     now_iso, item["event_id"]),
                )
                conn.commit()
            elif merge_result.get("ok") and merge_result.get("merged"):
                deploy = merge_result.get("deploy") or {}
                if deploy.get("attempted") and deploy.get("ok"):
                    deadline = (now + dt.timedelta(hours=LIVENESS_WINDOW_HOURS)).isoformat()
                    conn.execute(
                        "UPDATE triage_items SET state=?, liveness_deadline=?, deploy_expect_json=?, "
                        "note=NULL, updated_at=? WHERE event_id=?",
                        (STATE_LIVENESS_PENDING, deadline, json.dumps(deploy.get("expectedAlerts") or []),
                         now_iso, item["event_id"]),
                    )
                else:
                    reason = deploy.get("reason") or "merged; no deploy configured for this repo"
                    conn.execute(
                        "UPDATE triage_items SET state=?, note=?, updated_at=? WHERE event_id=?",
                        (STATE_MERGED, reason, now_iso, item["event_id"]),
                    )
                conn.commit()
            else:
                note = f"merge refused: {merge_result.get('error') or 'unknown reason'}"
                conn.execute(
                    "UPDATE triage_items SET state=?, note=?, updated_at=? WHERE event_id=?",
                    (STATE_MERGE_BLOCKED, note, now_iso, item["event_id"]),
                )
                conn.commit()
        fresh_item, fresh_event = _get_item(conn, item["event_id"]), _get_event(conn, item["event_id"])
        if fresh_item is not None and fresh_event is not None:
            sync_card(conn, [fresh_item], [fresh_event], policy, dry_run=False)


def maybe_check_liveness(conn: sqlite3.Connection, policy: dict[str, Any], now: dt.datetime,
                          *, dry_run: bool) -> None:
    """Step 10. The item must not close because the alert went quiet — a
    fully-down service is also quiet, same principle as
    resolve_quiet_grouped()/resolve_recovery_paired() above. Runs the
    repo's declared `liveness` probe (config/triage-policy.json's
    `repos.<repo>.liveness`, same closed-allowlist shape as `verb`/
    `evidence`) against the alert definition(s) captured at deploy time.
    Only a genuine POSITIVE match resolves the item. Past
    `liveness_deadline` with no positive match, the item REOPENS to `new`,
    carrying the full history (the pull request, the last liveness check) —
    the exact context that was missing when the same alert was
    re-diagnosed 61 times before this file existed."""
    items = conn.execute("SELECT * FROM triage_items WHERE state=?", (STATE_LIVENESS_PENDING,)).fetchall()
    for item in items:
        repo_entry = (policy.get("repos") or {}).get(item["repo"] or "") or {}
        key = repo_entry.get("liveness")
        gatherer = LIVENESS_ALLOWLIST.get(key) if key else None
        try:
            expected = json.loads(item["deploy_expect_json"] or "[]")
        except json.JSONDecodeError:
            expected = []

        if gatherer is None:
            live_ok, detail = False, f"no liveness key declared for repo {item['repo']!r}"
        else:
            ran_ok, result = _run_bounded(gatherer, expected, timeout=EVIDENCE_TIMEOUT)
            live_ok, detail = result if ran_ok else (False, f"liveness probe error: {result}")

        now_iso = _now_iso(now)
        if live_ok:
            if dry_run:
                print(f"[dry-run] would resolve {item['signature']} on confirmed liveness: {detail}")
                continue
            note = f"{LIVENESS_CONFIRMED_NOTE_PREFIX}{detail}"
            conn.execute(
                "UPDATE triage_items SET state=?, note=?, updated_at=? WHERE event_id=?",
                (STATE_RESOLVED, note, now_iso, item["event_id"]),
            )
            conn.commit()
            fresh_item, fresh_event = _get_item(conn, item["event_id"]), _get_event(conn, item["event_id"])
            if fresh_item is not None and fresh_event is not None:
                sync_card(conn, [fresh_item], [fresh_event], policy, dry_run=False)
            continue

        deadline = _parse_ts(item["liveness_deadline"])
        if deadline is not None and now < deadline:
            continue  # still inside the window — try again next run
        if dry_run:
            print(f"[dry-run] would REOPEN {item['signature']} — liveness never confirmed: {detail}")
            continue

        # Reopen carries history on the card itself (mirrors _dissolve_cluster()'s
        # own final-update-then-reset shape) — never through sync_card()/
        # render_card_blocks(), because the row is about to land back in
        # `new`, which must never be carded (see CARDED_STATES's own comment).
        history = (f"PR: {item['pr_url'] or '(none)'} — reopened, liveness never confirmed "
                   f"within the window. Last check: {detail}. Still failing as of "
                   f"{_fmt_ts(now_iso)}.")
        if item["card_channel"] and item["card_ts"]:
            token = resolve_slack_token()
            if token:
                blocks = [
                    {"type": "header", "text": {"type": "plain_text",
                     "text": ":recycle: Reopened — liveness never confirmed"}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": _escape(history)[:SECTION_TEXT_MAX]}},
                ]
                update_blocks(item["card_channel"], item["card_ts"], blocks,
                              "Reopened — liveness never confirmed", token)
        conn.execute(
            "UPDATE triage_items SET state=?, note=?, updated_at=? WHERE event_id=?",
            (STATE_NEW, history, now_iso, item["event_id"]),
        )
        conn.commit()


# --- propose_mappings() — step 8, the one LLM call in this file --------------
#
# See the module docstring's PROPOSE MAPPINGS paragraph for the full contract.

def _resolve_openai_base_url() -> str:
    """OPENAI_BASE_URL is a plain literal in .env.tpl (not a secret — it is
    already committed to this repo), so this only ever needs the inherited
    process env or that same template file, never secrets-run."""
    val = os.environ.get("OPENAI_BASE_URL", "")
    if val:
        return val
    try:
        text = (HERMES_HOME / ".env.tpl").read_text()
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("OPENAI_BASE_URL="):
            return line.split("=", 1)[1].split("#", 1)[0].strip()
    return ""


def _resolve_openai_api_key() -> str:
    """Mirrors resolve_slack_token()'s own hand-fallback shape exactly (env
    var first, else the secrets-run shim against the SAME op:// ref .env.tpl
    declares for OPENAI_API_KEY) — never a plaintext key, and never crosses
    an argv/`ps` boundary."""
    val = os.environ.get("OPENAI_API_KEY", "")
    if val:
        return val
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "/usr/bin:/bin")
    secrets_run = Path.home() / ".local" / "bin" / "secrets-run"
    try:
        r = subprocess.run(
            [str(secrets_run), "read", _OPENAI_API_KEY_REF],
            capture_output=True, text=True, timeout=15, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _discoverable_repos() -> set[str]:
    """Mirrors hermes-cc.sh's own resolve_repo()/discoverable() exactly: every
    top-level entry directly under `root` that is not dotted, not `deny`d,
    is a directory, and carries a `.git` subdirectory. A `map` proposal
    naming anything outside this set is dropped at apply time — never
    trusted from the model's own claim, or from the prompt's own list, alone
    (see BOUNDS THAT DO NOT MOVE in the module docstring)."""
    try:
        data = json.loads(DISPATCH_REPOS_JSON.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    root = Path(os.path.realpath(os.path.expanduser(data.get("root", "~/SourceRoot"))))
    deny = set(data.get("deny") or [])
    try:
        entries = os.listdir(root)
    except OSError:
        return set()
    out: set[str] = set()
    for name in entries:
        if name.startswith(".") or name in deny:
            continue
        p = root / name
        if p.is_dir() and (p / ".git").exists():
            out.add(name)
    return out


def _signature_first_seen(row: sqlite3.Row) -> dt.datetime | None:
    """When this SIGNATURE was first seen, not when its current open period began.

    A grouped source's payload carries `ts_first` — a unix timestamp set the very
    first time the dedup key appeared and never reset — while `events.first_seen`
    is rewritten every time reconcile() reopens a resolved row. Any question of
    the form "has this been going on a while" must read the former; the latter
    answers a different question and understates it badly."""
    payload = _safe_json(row["payload_json"] if "payload_json" in row.keys() else None)
    raw = payload.get("ts_first")
    if raw is None:
        return None
    try:
        return dt.datetime.fromtimestamp(float(raw), dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _propose_mapping_candidates(conn: sqlite3.Connection, policy: dict[str, Any],
                                 now: dt.datetime) -> list[sqlite3.Row]:
    """Every item classify() found no rule for, whose event is at least
    `proposeMappingsAgeDays` old, excluding anything the model already said
    `unsure` about within PROPOSE_UNSURE_COOLDOWN_DAYS — oldest first, capped
    at PROPOSE_MAPPINGS_MAX_SIGNATURES.

    Deliberately NOT restricted to `state = new`. Keying the pool on current
    state made this whole pass inert: resolve_quiet_grouped() runs earlier in
    the same cycle, so a grouped `slack_alert` signature flips to `resolved` on
    the 2h quiet timer long before this query sees it. Measured against the
    live DB, 16 of 19 unmapped signatures vanished that way and the other 3
    were younger than the age floor — zero candidates, permanently.

    The question this pass answers is "has this signature ever been mapped",
    which is a property of the POLICY FILE, not of an item's lifecycle. A
    signature that resolved quietly is still unmapped and will fire again; that
    is precisely the case worth mapping. `ignored` is the one state excluded —
    a human or a rule already decided it deliberately, and re-proposing it
    would relitigate a settled call. Items are collapsed per signature, since
    the same signature can own several rows over time."""
    age_days = policy["proposeMappingsAgeDays"]
    # Age alone is the wrong test on its own. The floor exists to avoid spending a
    # proposal on a one-off, but a signature that has already fired many times is
    # demonstrably not one — `homelab-temperature-above-threshold` had 25
    # occurrences in 5 days and would have sat under a 7-day floor while paging
    # the whole time. Either signal qualifies it: old enough to have proven
    # persistent, OR frequent enough to have proven the same thing faster.
    min_occurrences = PROPOSE_MAPPINGS_MIN_OCCURRENCES
    unsure_cutoff = now - dt.timedelta(days=PROPOSE_UNSURE_COOLDOWN_DAYS)
    rows = conn.execute(
        "SELECT ti.event_id, ti.signature, ti.occurrences, ti.first_seen, ti.last_seen, "
        "ti.propose_unsure_at, e.title, e.payload_json FROM triage_items ti JOIN events e ON e.id = ti.event_id "
        "WHERE ti.state != ? AND ti.repo IS NULL AND ti.verb IS NULL "
        "GROUP BY ti.signature ORDER BY MIN(ti.first_seen) ASC",
        (STATE_IGNORED,),
    ).fetchall()
    candidates: list[sqlite3.Row] = []
    for row in rows:
        # Age must be measured from when the SIGNATURE was first seen, not from
        # when this row's current open period began. For a grouped source those
        # differ by months: `homelab-temperature-above-threshold` carries
        # ts_first = 2026-04-30 in its payload while events.first_seen reads
        # 2026-09-04, because reconcile() reopens a resolved row with a fresh
        # first_seen. Reading the row's own column made a 132-day-old recurring
        # signature look five days old and kept it under every floor.
        first_seen = _signature_first_seen(row) or _parse_ts(row["first_seen"])
        old_enough = first_seen is not None and now - first_seen >= dt.timedelta(days=age_days)
        # occurrences is the LAST poll's batch count, not a cumulative total, so
        # it cannot stand in for persistence on its own — it is a fast path for a
        # signature that fired hard in one window, nothing more.
        frequent_enough = (row["occurrences"] or 0) >= min_occurrences
        if not (old_enough or frequent_enough):
            continue
        unsure_at = _parse_ts(row["propose_unsure_at"])
        if unsure_at is not None and unsure_at > unsure_cutoff:
            continue
        candidates.append(row)
        if len(candidates) >= PROPOSE_MAPPINGS_MAX_SIGNATURES:
            break
    return candidates


def _build_propose_mappings_prompt(candidates: list[sqlite3.Row], repo_names: list[str]) -> str:
    lines = [
        "You maintain a signature -> repo mapping table for an infrastructure alert "
        "triage system. Each signature below has fired repeatedly for at least a week "
        "with no owning repo, so it never escalates and never gets a card.",
        "",
        "For EACH signature, decide exactly ONE of:",
        '  {"action": "ignore", "reason": "<one line>"}  — a known-benign pattern or a '
        "genuine recovery, safe to silence forever",
        '  {"action": "map", "repo": "<repo name>", "reason": "<one line>"}  — future '
        "occurrences should open a read-only investigation of this repo",
        '  {"action": "unsure"}  — you cannot confidently decide either way',
        "",
        "Valid repo names — a name outside this list is dropped, never applied:",
        ", ".join(repo_names) if repo_names else "(none discoverable)",
        "",
        "Respond with STRICT JSON ONLY: a single JSON object keyed by the EXACT signature "
        "string, each value one of the three shapes above. No prose, no markdown fences, "
        "no extra keys, no signatures other than the ones listed below.",
        "",
        "Signatures:",
    ]
    for c in candidates:
        lines.append(
            f"- signature: {c['signature']}\n"
            f"  title: {c['title'] or ''}\n"
            f"  occurrences: {c['occurrences']}\n"
            f"  first_seen: {c['first_seen']}\n"
            f"  last_seen: {c['last_seen']}"
        )
    return "\n".join(lines)


def _call_propose_mappings_model(prompt: str) -> dict[str, Any] | None:
    """The ONLY LLM call in this file. One request, strict JSON, hard-bounded
    on every axis this loop can bound (timeout, output tokens, and the
    caller's own cap on how many signatures went into the prompt). ANY
    failure — unresolved secrets, network, timeout, non-2xx, unexpected
    response shape, or unparseable JSON — is caught here and returns None;
    propose_mappings() logs to stderr and moves on. This loop must never
    depend on this call succeeding."""
    base_url = _resolve_openai_base_url()
    api_key = _resolve_openai_api_key()
    if not base_url or not api_key:
        print("triage: propose_mappings — OPENAI_BASE_URL/OPENAI_API_KEY unresolved, skipping",
              file=sys.stderr)
        return None
    body = json.dumps({
        "model": PROPOSE_MAPPINGS_MODEL,
        "messages": [
            {"role": "system", "content": "You output strict JSON only — no prose, no markdown fences."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": PROPOSE_MAPPINGS_MAX_OUTPUT_TOKENS,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=PROPOSE_MAPPINGS_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError) as e:
        print(f"triage: propose_mappings — model call failed: {e}", file=sys.stderr)
        return None
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        print(f"triage: propose_mappings — unexpected response shape: {str(data)[:300]}", file=sys.stderr)
        return None
    content = (content or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content[:4].lower() == "json":
            content = content[4:]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"triage: propose_mappings — response was not valid JSON: {e}", file=sys.stderr)
        return None
    if not isinstance(parsed, dict):
        print("triage: propose_mappings — response JSON was not an object, skipping", file=sys.stderr)
        return None
    return parsed


def _apply_propose_mappings(conn: sqlite3.Connection, now: dt.datetime, response: dict[str, Any],
                             candidates_by_sig: dict[str, sqlite3.Row],
                             valid_repos: set[str]) -> list[dict[str, str]]:
    """Applies each decision for a signature actually in THIS batch (a
    signature the model invents is ignored — it was never asked about). A
    `map` repo is re-checked against `valid_repos` (the SAME discovery
    hermes-cc.sh's own resolve_repo() uses) AND the deny list — never
    trusted from the model alone. `unsure` writes a cooldown marker directly
    to triage_items; `map`/`ignore` write NOTHING to triage_items here —
    they only ever become policy entries, picked up by classify() on a
    LATER run, exactly like a hand-written rule would be. Returns the
    applied `map`/`ignore` decisions only (for the policy file + digest —
    `unsure` is not "applied", it is deferred)."""
    applied: list[dict[str, str]] = []
    now_iso = _now_iso(now)
    denied = _denied_repos()
    for sig, decision in response.items():
        row = candidates_by_sig.get(sig)
        if row is None:
            continue
        if not isinstance(decision, dict):
            print(f"triage: propose_mappings — malformed decision for {sig!r}, dropping", file=sys.stderr)
            continue
        action = decision.get("action")
        reason = decision.get("reason") if isinstance(decision.get("reason"), str) else ""
        if action == "ignore":
            applied.append({"signature": sig, "action": "ignore", "reason": reason})
        elif action == "map":
            repo = decision.get("repo")
            if not isinstance(repo, str) or repo not in valid_repos or repo in denied:
                print(f"triage: propose_mappings — dropping map proposal for {sig!r}: repo "
                      f"{repo!r} does not resolve under the dispatch root or is denied", file=sys.stderr)
                continue
            applied.append({"signature": sig, "action": "map", "repo": repo, "reason": reason})
        elif action == "unsure":
            conn.execute(
                "UPDATE triage_items SET propose_unsure_at=?, updated_at=? WHERE event_id=?",
                (now_iso, now_iso, row["event_id"]),
            )
        else:
            print(f"triage: propose_mappings — unknown action {action!r} for {sig!r}, dropping", file=sys.stderr)
    conn.commit()
    return applied


def _dump_policy_json(data: dict[str, Any]) -> str:
    """Serializes the policy file preserving top-level key order, rendering
    `_readme`/`rules`/`ignore` one array element per line (the file's own
    hand-authored style) rather than json.dump's default fully-expanded
    nesting, which would rewrite every untouched rule and turn one new line
    into a whole-file diff."""
    parts = []
    for key, value in data.items():
        if isinstance(value, list):
            if not value:
                rendered = "[]"
            else:
                items = ",\n    ".join(json.dumps(v) for v in value)
                rendered = "[\n    " + items + "\n  ]"
        else:
            rendered = json.dumps(value, indent=2).replace("\n", "\n  ")
        parts.append(f"  {json.dumps(key)}: {rendered}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def _write_policy_additions(applied: list[dict[str, str]], now: dt.datetime) -> bool:
    """Reads the RAW policy JSON (never load_policy()'s normalized/defaulted
    view — that would drop unknown keys and reorder nothing back), appends
    one stamped rules/ignore entry per applied proposal, and writes it back
    preserving `_readme` and key order. False (no-op) on any read/parse
    failure or an empty `applied` list."""
    if not applied:
        return False
    try:
        data = json.loads(POLICY_PATH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"triage: propose_mappings — cannot read policy file to apply proposals: {e}", file=sys.stderr)
        return False
    stamp = _now_iso(now)
    rules = list(data.get("rules") or [])
    ignore = list(data.get("ignore") or [])
    for item in applied:
        if item["action"] == "map":
            rules.append({
                "match": item["signature"],
                "repo": item["repo"],
                "proposedAt": stamp,
                "proposedBy": "triage-auto",
                "reason": item["reason"],
            })
        elif item["action"] == "ignore":
            ignore.append({
                "match": item["signature"],
                "proposedAt": stamp,
                "proposedBy": "triage-auto",
                "reason": item["reason"],
            })
    data["rules"] = rules
    data["ignore"] = ignore
    POLICY_PATH.write_text(_dump_policy_json(data))
    return True


def _policy_git_rel_path() -> Path | None:
    try:
        return POLICY_PATH.resolve().relative_to(TRIAGE_REPO_DIR.resolve())
    except (OSError, ValueError):
        return None


def _policy_path_is_dirty(rel: Path) -> bool:
    """True if config/triage-policy.json ALREADY carries a pending
    staged-or-unstaged change before this run's own write — checked before
    _write_policy_additions() ever touches the file, so a human's own
    in-progress edit is never swept into an auto-authored commit. Also true
    (fail closed) if `git status` itself cannot be run at all."""
    try:
        res = subprocess.run(
            ["git", "-C", str(TRIAGE_REPO_DIR), "status", "--porcelain", "--", str(rel)],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    if res.returncode != 0:
        return True
    return bool(res.stdout.strip())


def _git_commit_policy_file(rel: Path, applied: list[dict[str, str]]) -> None:
    """`git add` + `git commit` ONLY config/triage-policy.json, in this
    repo's own checkout — never `git add -A`, never `git push` (a human
    sends anything further). The file is symlinked live into
    ~/.hermes/config/, so the change already took effect the moment
    _write_policy_additions() returned; committing turns that into a
    reviewable diff instead of the dirty-working-tree drift this repo has
    been bitten by before (see CLAUDE.md "After any edit: commit here"). No
    lock is taken — this is the only writer of this file — the dirtiness
    check the caller already did before writing is what keeps this from
    sweeping an unrelated pending edit into an auto-authored commit."""
    repo_dir = str(TRIAGE_REPO_DIR)
    summary = "; ".join(
        f"{a['signature']} -> {a['repo']}" if a["action"] == "map" else f"{a['signature']} -> ignore"
        for a in applied
    )
    msg = f"chore(triage-policy): auto-propose {len(applied)} mapping(s)\n\n{summary}"
    add = subprocess.run(["git", "-C", repo_dir, "add", "--", str(rel)],
                          capture_output=True, text=True, timeout=30)
    if add.returncode != 0:
        print(f"triage: propose_mappings — git add failed: {add.stderr.strip()}", file=sys.stderr)
        return
    commit = subprocess.run(["git", "-C", repo_dir, "commit", "-m", msg, "--", str(rel)],
                             capture_output=True, text=True, timeout=30)
    if commit.returncode != 0:
        print(f"triage: propose_mappings — git commit failed: {commit.stderr.strip()}", file=sys.stderr)


def propose_mappings(conn: sqlite3.Connection, policy: dict[str, Any], now: dt.datetime,
                      *, dry_run: bool) -> list[dict[str, str]]:
    """Step 8 — see the module docstring's PROPOSE MAPPINGS paragraph for the
    full contract. Returns the applied map/ignore proposals (possibly
    empty), so run() can hand them to maybe_post_daily_digest() for
    announcement the same day. Under --dry-run this makes zero calls of any
    kind (model, git) and returns []  — matching every other externally
    visible action in this file's DRY-RUN CONTRACT."""
    if dry_run:
        return []

    row = conn.execute("SELECT value FROM cursors WHERE key=?", (PROPOSE_MAPPINGS_CURSOR_KEY,)).fetchone()
    if row is not None:
        last_run = _parse_ts(row["value"])
        if last_run is not None and now - last_run < dt.timedelta(hours=24):
            return []

    candidates = _propose_mapping_candidates(conn, policy, now)
    # The cursor is a once-per-24h BUDGET, not a "keep retrying until it
    # succeeds" loop — stamped here, before the call, so a failed call still
    # counts against today's attempt rather than hammering the endpoint on
    # every 10-minute cycle until one happens to succeed.
    now_iso = _now_iso(now)
    conn.execute(
        "INSERT INTO cursors(key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (PROPOSE_MAPPINGS_CURSOR_KEY, now_iso, now_iso),
    )
    conn.commit()
    if not candidates:
        return []

    valid_repos = _discoverable_repos()
    prompt = _build_propose_mappings_prompt(candidates, sorted(valid_repos))
    response = _call_propose_mappings_model(prompt)
    if response is None:
        return []  # already logged by the call itself

    candidates_by_sig = {c["signature"]: c for c in candidates}
    applied = _apply_propose_mappings(conn, now, response, candidates_by_sig, valid_repos)
    if not applied:
        return []

    rel = _policy_git_rel_path()
    if rel is None:
        print(f"triage: propose_mappings — policy file is not inside a git checkout at "
              f"{TRIAGE_REPO_DIR}, skipping this run's proposals entirely", file=sys.stderr)
        return []
    if _policy_path_is_dirty(rel):
        print(f"triage: propose_mappings — {rel} already has a pending change, skipping this "
              "run's proposals entirely rather than sweeping it into an auto-authored commit",
              file=sys.stderr)
        return []
    if not _write_policy_additions(applied, now):
        return []
    _git_commit_policy_file(rel, applied)
    return applied


# --- unmapped-signature digest -------------------------------------------------

def _fetch_note_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT ti.signature, e.title FROM triage_items ti JOIN events e ON e.id = ti.event_id "
        "WHERE ti.state=? ORDER BY ti.updated_at DESC",
        (STATE_NOTE,),
    ).fetchall()


def maybe_post_daily_digest(conn: sqlite3.Connection, policy: dict[str, Any], unmapped: set[str],
                             now: dt.datetime, *, dry_run: bool,
                             auto_mapped: list[dict[str, str]] | None = None) -> None:
    """One Slack message, at most once per UTC day, with up to three
    sections: unmapped signatures (no policy rule matched — see classify()),
    STATE_NOTE rows (unstructured #alerts prose that might be an unactioned
    root cause — see that state's own docstring), and whatever
    propose_mappings() just auto-added THIS run (see PROPOSE MAPPINGS) — the
    latter is how an auto-authored policy commit gets ANNOUNCED rather than
    only discovered later in `git log`. All three are silent by default;
    this is the only place any of them becomes visible."""
    auto_mapped = auto_mapped or []
    notes = _fetch_note_rows(conn)
    if not unmapped and not notes and not auto_mapped:
        return
    today = now.date().isoformat()
    row = conn.execute("SELECT value FROM cursors WHERE key=?", (DAILY_DIGEST_CURSOR_KEY,)).fetchone()
    if row and row["value"] == today:
        return

    lines: list[str] = []
    if auto_mapped:
        lines.append("*Auto-proposed triage-policy changes* — added to `triage-policy.json` and "
                      "committed this run (`proposedBy: triage-auto`):")
        for a in auto_mapped:
            target = f"repo `{a['repo']}`" if a["action"] == "map" else "`ignore`"
            reason = a.get("reason") or "(no reason given)"
            lines.append(f"- `{a['signature']}` -> {target} — {reason}")
    if unmapped:
        if lines:
            lines.append("")
        sigs = sorted(unmapped)
        lines.append("*Unmapped triage signatures* — no rule in `triage-policy.json`, so these never escalate:")
        lines.extend(f"- `{s}`" for s in sigs[:20])
        if len(sigs) > 20:
            lines.append(f"… and {len(sigs) - 20} more")
    if notes:
        if lines:
            lines.append("")
        lines.append("*Unstructured notes in #alerts* — possible root causes nobody actioned:")
        for r in notes[:20]:
            title = (r["title"] or "").strip()
            truncated = title[:140] + ("…" if len(title) > 140 else "")
            lines.append(f"- `{r['signature']}` — {truncated}")
        if len(notes) > 20:
            lines.append(f"… and {len(notes) - 20} more")

    text = "\n".join(lines)
    channel = _card_channel(policy)
    if dry_run:
        print(f"[dry-run] would post daily digest ({len(unmapped)} unmapped, {len(notes)} notes, "
              f"{len(auto_mapped)} auto-mapped) to {channel}")
        return
    token = resolve_slack_token()
    if not token:
        print("triage: no Slack token, cannot post daily digest", file=sys.stderr)
        return
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text[:SECTION_TEXT_MAX]}}]
    ok, _ts = post_blocks(channel, blocks, text, token)
    if not ok:
        print("triage: daily digest post failed", file=sys.stderr)
        return
    conn.execute(
        "INSERT INTO cursors(key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (DAILY_DIGEST_CURSOR_KEY, today, _now_iso(now)),
    )
    conn.commit()


# --- the loop --------------------------------------------------------------

def run(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    policy = load_policy()

    ingest(conn, now)
    reopen_if_needed(conn, now)
    unsnooze_if_expired(conn, now)
    unmapped = classify(conn, policy, now)
    apply_resolutions(conn, now)
    resolve_recovery_paired(conn, policy, now, dry_run=dry_run)
    resolve_quiet_grouped(conn, policy, now)
    maybe_dissolve_clusters(conn, now, dry_run=dry_run)

    escalate(conn, policy, now, dry_run=dry_run)
    run_verbs(conn, policy, now, dry_run=dry_run)

    # Steps 6-10 — verdict -> implement -> validate -> merge -> deploy ->
    # verify. Each is a poll-once-per-run step over its own state, so this
    # ordering (implement before validation before liveness) lets an item
    # that crossed a stage earlier THIS SAME RUN also be picked up by the
    # next stage rather than waiting a full 10 minutes — never required for
    # correctness (each stage re-derives its own eligibility from the DB
    # every run regardless), just fewer idle cycles.
    maybe_auto_implement(conn, policy, now, dry_run=dry_run)
    poll_implement_jobs(conn, policy, now, dry_run=dry_run)
    poll_validation_jobs(conn, policy, now, dry_run=dry_run)
    maybe_check_liveness(conn, policy, now, dry_run=dry_run)

    for _key, members in _cluster_groups(conn).items():
        members = sorted(members, key=lambda r: r["event_id"])
        event_rows = [_get_event(conn, m["event_id"]) for m in members]
        if any(er is None for er in event_rows):
            continue
        sync_card(conn, members, event_rows, policy, dry_run=dry_run)

    # Step 8 — the one LLM call in this file, at most once per 24h. Runs
    # AFTER classify() so `unmapped` above already reflects this run's own
    # rule matching, and its result feeds directly into today's digest below
    # rather than waiting for a separate delivery mechanism.
    auto_mapped = propose_mappings(conn, policy, now, dry_run=dry_run)

    maybe_post_daily_digest(conn, policy, unmapped, now, dry_run=dry_run, auto_mapped=auto_mapped)
    return 0


# --- CLI verbs: --snooze / --ignore / --reopen / --list ------------------------

def _arg_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    return argv[idx + 1] if idx + 1 < len(argv) else None


def cmd_snooze(conn: sqlite3.Connection, argv: list[str], now: dt.datetime) -> int:
    signature = _arg_value(argv, "--snooze")
    hours_s = _arg_value(argv, "--hours")
    if not signature:
        print("triage: --snooze needs a signature", file=sys.stderr)
        return 2
    try:
        hours = float(hours_s) if hours_s else 24.0
    except ValueError:
        print(f"triage: --hours must be a number, got {hours_s!r}", file=sys.stderr)
        return 2
    until = (now + dt.timedelta(hours=hours)).isoformat()
    cur = conn.execute(
        "UPDATE triage_items SET state=?, snoozed_until=?, updated_at=? WHERE signature=?",
        (STATE_SNOOZED, until, _now_iso(now), signature),
    )
    conn.commit()
    if cur.rowcount == 0:
        print(f"triage: no triage item for signature {signature!r}", file=sys.stderr)
        return 1
    print(f"snoozed {signature} until {until}")
    return 0


def cmd_ignore(conn: sqlite3.Connection, argv: list[str], now: dt.datetime) -> int:
    signature = _arg_value(argv, "--ignore")
    if not signature:
        print("triage: --ignore needs a signature", file=sys.stderr)
        return 2
    cur = conn.execute(
        "UPDATE triage_items SET state=?, snoozed_until=NULL, updated_at=? WHERE signature=?",
        (STATE_IGNORED, _now_iso(now), signature),
    )
    conn.commit()
    if cur.rowcount == 0:
        print(f"triage: no triage item for signature {signature!r}", file=sys.stderr)
        return 1
    print(f"ignored {signature}")
    return 0


def cmd_reopen(conn: sqlite3.Connection, argv: list[str], now: dt.datetime) -> int:
    signature = _arg_value(argv, "--reopen")
    if not signature:
        print("triage: --reopen needs a signature", file=sys.stderr)
        return 2
    cur = conn.execute(
        "UPDATE triage_items SET state=?, snoozed_until=NULL, updated_at=? WHERE signature=?",
        (STATE_NEW, _now_iso(now), signature),
    )
    conn.commit()
    if cur.rowcount == 0:
        print(f"triage: no triage item for signature {signature!r}", file=sys.stderr)
        return 1
    print(f"reopened {signature}")
    return 0


def cmd_list(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT signature, state, repo, verb, occurrences, first_seen FROM triage_items "
        "WHERE state != ? ORDER BY updated_at DESC",
        (STATE_RESOLVED,),
    ).fetchall()
    if not rows:
        print("no open triage items")
        return 0
    for r in rows:
        print(f"{r['state']:<13} {r['signature']:<70} repo={r['repo'] or r['verb'] or '-'} "
              f"occurrences={r['occurrences']} since={r['first_seen']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    _apply_db_override(argv)
    now = dt.datetime.now(dt.timezone.utc)
    conn = db_connect()
    try:
        if "--snooze" in argv:
            return cmd_snooze(conn, argv, now)
        if "--ignore" in argv:
            return cmd_ignore(conn, argv, now)
        if "--reopen" in argv:
            return cmd_reopen(conn, argv, now)
        if "--list" in argv:
            return cmd_list(conn)
        return run(conn, dry_run="--dry-run" in argv)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
