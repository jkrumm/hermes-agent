#!/usr/bin/env python3
"""Regression suite for scripts/triage.py — the act-loop that turns
deduplicated watchdog.db events into one durable, updated-in-place Slack card
per problem (or per CLUSTER of co-occurring problems in one repo), with a
real sideclaw investigation attached once a signature repeats or stays open.

HOUSE CONVENTION, not pytest: this repo's `~/.hermes/hermes-agent/venv` has no
pytest installed (see docs/patches.md's "unrunnable here anyway" note) and
every other tests/test_*.py in this repo is a hand-rolled main() run with a
bare interpreter — test_dispatch_sweep.py and test_hermes_cc.py among them.
Every check below is still a plain `def test_*(): assert ...` function with no
arguments and no fixtures, so this file is ALSO valid standalone pytest input
if pytest is ever installed in this venv (`python3 -m pytest tests/test_triage.py -q`
would collect and run every one of them unmodified) — main() just discovers
and calls them itself in the meantime via reflection, matching every other
test file's "run with a bare interpreter" contract.

Run:

    ~/.hermes/hermes-agent/venv/bin/python3 tests/test_triage.py
    # or, if pytest is ever installed in that venv:
    ~/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/test_triage.py -q

Exit status is 0 only when every case matches.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import json
import shutil
import sqlite3
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIAGE_PATH = REPO_ROOT / "scripts" / "triage.py"

_spec = importlib.util.spec_from_file_location("triage", TRIAGE_PATH)
assert _spec is not None and _spec.loader is not None
triage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(triage)

# Also loaded directly (not just through triage.py's own dynamic import) —
# test_op_refs_raw_fallback_dedups_across_timestamps below covers
# watchdog-poll.py's own fix in isolation, with no DB/Slack involved.
WATCHDOG_POLL_PATH = REPO_ROOT / "scripts" / "watchdog-poll.py"
_wp_spec = importlib.util.spec_from_file_location("watchdog_poll", WATCHDOG_POLL_PATH)
assert _wp_spec is not None and _wp_spec.loader is not None
watchdog_poll = importlib.util.module_from_spec(_wp_spec)
_wp_spec.loader.exec_module(watchdog_poll)


# --- fixtures ------------------------------------------------------------------

# Match targets are `source:external_id` — these fixture events use external_ids
# that already read as the intended signature, so the rules below match the
# first target directly without needing the title-normalized fallback (that
# path gets its own dedicated test, test_uk_maps_via_title_not_external_id).
DEFAULT_POLICY = {
    "cardChannel": "C0TESTCHAN01",
    "minOccurrences": 1,
    "minOpenMinutes": 30,
    "cooldownHours": 6,
    "ignoreUnstructuredSlackProse": False,
    "rules": [{"match": "slack_alert:sig-*", "repo": "demo-repo"}],
    "ignore": ["slack_alert:ignoreme-*"],
}


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data))


@contextlib.contextmanager
def _triage_env(*, policy: dict[str, Any] | None = None, deny: list[str] | None = None):
    """Stand up a throwaway watchdog.db + policy + dispatch-repos.json fixture,
    point scripts/triage.py's module globals at them, stub Slack (post_blocks/
    update_blocks/resolve_slack_token) to record calls with no network, and
    restore every patched attribute on exit. Yields (conn, ctx) where ctx
    exposes the recorded Slack calls and lets a test swap in its own
    `_run_hermes_cc_dispatch` stub."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="triage-test-"))
    saved = {
        "DB_PATH": triage.DB_PATH,
        "POLICY_PATH": triage.POLICY_PATH,
        "DISPATCH_REPOS_JSON": triage.DISPATCH_REPOS_JSON,
        "HERMES_CC_BIN": triage.HERMES_CC_BIN,
        "resolve_slack_token": triage.resolve_slack_token,
        "post_blocks": triage.post_blocks,
        "update_blocks": triage.update_blocks,
        "_run_hermes_cc_dispatch": triage._run_hermes_cc_dispatch,
        "MAX_OPEN_INVESTIGATIONS": triage.MAX_OPEN_INVESTIGATIONS,
        "DAILY_INVESTIGATE_BUDGET": triage.DAILY_INVESTIGATE_BUDGET,
        "VERB_ALLOWLIST": dict(triage.VERB_ALLOWLIST),
    }
    try:
        triage.DB_PATH = tmp_dir / "watchdog.db"
        triage.POLICY_PATH = tmp_dir / "triage-policy.json"
        triage.DISPATCH_REPOS_JSON = tmp_dir / "dispatch-repos.json"
        _write_json(triage.POLICY_PATH, policy if policy is not None else DEFAULT_POLICY)
        _write_json(triage.DISPATCH_REPOS_JSON, {"root": "~/SourceRoot", "deny": deny or []})

        posted: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        _ts_counter = {"n": 0}

        def _fake_post(channel, blocks, text_fallback, token):
            _ts_counter["n"] += 1
            ts = f"1000.{_ts_counter['n']:06d}"
            posted.append({"channel": channel, "blocks": blocks, "text": text_fallback, "ts": ts})
            return True, ts

        def _fake_update(channel, ts, blocks, text_fallback, token):
            updated.append({"channel": channel, "ts": ts, "blocks": blocks, "text": text_fallback})
            return True, ts

        triage.resolve_slack_token = lambda: "test-token"
        triage.post_blocks = _fake_post
        triage.update_blocks = _fake_update

        conn = triage.db_connect()

        class Ctx:
            def __init__(self):
                self.posted = posted
                self.updated = updated
                self.tmp_dir = tmp_dir

            def total_calls(self) -> int:
                return len(self.posted) + len(self.updated)

        yield conn, Ctx()
        conn.close()
    finally:
        for k, v in saved.items():
            setattr(triage, k, v)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _insert_event(conn: sqlite3.Connection, *, source: str, external_id: str, title: str,
                   first_seen: dt.datetime, reminder_count: int = 0, resolved_at: str | None = None,
                   payload: dict[str, Any] | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO events(source, external_id, title, url, payload_json, first_seen, "
        "reminder_count, resolved_at) VALUES (?,?,?,?,?,?,?,?)",
        (source, external_id, title, "", json.dumps(payload or {}), first_seen.isoformat(),
         reminder_count, resolved_at),
    )
    conn.commit()
    return cur.lastrowid


def _fake_dispatcher(conn: sqlite3.Connection, calls: list[dict[str, Any]], *, ok: bool = True):
    """Replaces triage._run_hermes_cc_dispatch for tests that care about
    triage.py's OWN orchestration (dedup, clustering, caps, edges) rather
    than the exact subprocess/stdin mechanics of hermes-cc.sh itself — see
    test_dispatch_brief_on_stdin_and_capped for the one test that exercises
    the real subprocess path instead. Mirrors hermes-cc.sh's record_dispatch()
    INSERT exactly, so escalate_cluster()'s own `SELECT id FROM dispatches
    WHERE job_id=?` lookup (the events.dispatch_id edge) behaves exactly as
    it would against the real script."""
    counter = {"n": 0}

    def _dispatch(*, repo, brief, event_id, channel, thread_ts, timeout):
        counter["n"] += 1
        calls.append({"repo": repo, "brief": brief, "event_id": event_id,
                       "channel": channel, "thread_ts": thread_ts})
        if not ok:
            return None
        job_id = f"job-{counter['n']:06d}"
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO dispatches(job_id,tier,repo,brief,why,origin_channel,origin_thread_ts,"
            "origin_event_id,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (job_id, "investigate", repo, brief, None, channel, thread_ts, event_id, "queued", now_iso),
        )
        conn.commit()
        return {"verb": "dispatch", "ok": True, "jobId": job_id, "repo": repo,
                "tier": "investigate", "status": "queued"}

    return _dispatch


NOW = dt.datetime.now(dt.timezone.utc)
OLD = NOW - dt.timedelta(hours=1)


# --- tests -----------------------------------------------------------------

def test_repeated_signature_one_card_one_investigation():
    with _triage_env() as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="sig-a", title="Alert A", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)

        assert triage.run(conn, dry_run=False) == 0
        assert triage.run(conn, dry_run=False) == 0  # a second cron cycle, nothing changed

        assert len(calls) == 1, f"expected exactly one dispatch, got {len(calls)}"
        assert len(ctx.posted) == 1, f"expected exactly one initial card post, got {len(ctx.posted)}"
        assert len(ctx.updated) == 0, f"expected zero card updates (posted directly in investigating state)"

        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_INVESTIGATING
        assert item["dispatch_job"] == "job-000001"


def test_new_state_item_gets_no_card():
    """The core fix for correction #2: an item still in `new` — mapped or
    not — must never be carded, only the once-a-day unmapped digest speaks
    for it."""
    policy = dict(DEFAULT_POLICY, minOccurrences=5, minOpenMinutes=999999)
    with _triage_env(policy=policy) as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="sig-fresh", title="Not yet eligible", first_seen=NOW)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        assert calls == []
        assert ctx.total_calls() == 0, "an item still in `new` must never get a card"
        item = conn.execute("SELECT state FROM triage_items").fetchone()
        assert item["state"] == triage.STATE_NEW


def test_all_unmapped_backlog_posts_zero_slack_calls():
    """An empty/non-matching policy must not turn into a wall of cards —
    the exact failure mode (37 cards) this correction exists to remove. The
    digest is pre-seeded as already-posted-today so this asserts truly zero
    Slack calls of any kind, not just zero cards."""
    policy = dict(DEFAULT_POLICY, rules=[])
    with _triage_env(policy=policy) as (conn, ctx):
        for i in range(5):
            _insert_event(conn, source="slack_alert", external_id=f"sig-nowhere-{i}",
                           title=f"Nowhere {i}", first_seen=OLD)
        # Pre-seed today's unmapped-digest cursor so that separate, deliberate
        # mechanism doesn't count against "zero Slack calls" here.
        today = NOW.date().isoformat()
        now_iso = NOW.isoformat()
        conn.execute("INSERT INTO cursors(key, value, updated_at) VALUES (?, ?, ?)",
                     (triage.DAILY_DIGEST_CURSOR_KEY, today, now_iso))
        conn.commit()

        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        assert calls == []
        assert ctx.total_calls() == 0, f"expected zero Slack calls, got {ctx.total_calls()}"


def test_both_missing_edges_are_written():
    with _triage_env() as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="sig-edges", title="Edges", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)

        event_row = triage._get_event(conn, eid)
        assert event_row["dispatch_id"] is not None, "events.dispatch_id was never written"

        d = conn.execute(
            "SELECT origin_event_id FROM dispatches WHERE id=?", (event_row["dispatch_id"],)
        ).fetchone()
        assert d is not None
        assert d["origin_event_id"] == eid, "dispatches.origin_event_id was never written"


def test_min_occurrences_withholds():
    policy = dict(DEFAULT_POLICY, minOccurrences=5, minOpenMinutes=999999)
    with _triage_env(policy=policy) as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="sig-thresh", title="Low count",
                             first_seen=NOW, reminder_count=0)  # occurrences resolves to 1
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        assert calls == [], "should not have escalated below minOccurrences and inside minOpenMinutes"
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_NEW


def test_min_open_minutes_withholds_then_allows():
    policy = dict(DEFAULT_POLICY, minOccurrences=999, minOpenMinutes=30)
    with _triage_env(policy=policy) as (conn, ctx):
        fresh = NOW - dt.timedelta(minutes=5)
        eid = _insert_event(conn, source="slack_alert", external_id="sig-age", title="Too fresh", first_seen=fresh)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        assert calls == [], "should not escalate before minOpenMinutes has elapsed"

        old_enough = NOW - dt.timedelta(minutes=45)
        conn.execute("UPDATE events SET first_seen=? WHERE id=?", (old_enough.isoformat(), eid))
        conn.execute("UPDATE triage_items SET first_seen=? WHERE event_id=?", (old_enough.isoformat(), eid))
        conn.commit()
        triage.run(conn, dry_run=False)
        assert len(calls) == 1, "should escalate once minOpenMinutes has elapsed"


def test_snooze_withholds_escalation():
    with _triage_env() as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="sig-snooze", title="Snoozed", first_seen=OLD)
        triage.ingest(conn, NOW)
        item = triage._get_item(conn, eid)
        rc = triage.cmd_snooze(conn, ["--snooze", item["signature"], "--hours", "6"], NOW)
        assert rc == 0

        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        assert calls == [], "a snoozed item must never escalate"
        item2 = triage._get_item(conn, eid)
        assert item2["state"] == triage.STATE_SNOOZED
        assert ctx.total_calls() == 0, "a snoozed item must never get a card"


def test_ignore_policy_never_cards_or_escalates():
    with _triage_env() as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="ignoreme-recovery", title="All good now",
                       first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        assert calls == []
        assert ctx.total_calls() == 0, "an ignored signature must never get a card"
        row = conn.execute("SELECT state FROM triage_items").fetchone()
        assert row["state"] == triage.STATE_IGNORED


def test_unstructured_prose_lands_in_note_not_ignored():
    """Correction #1, highest priority: unstructured #alerts prose must
    never be silently dropped into `ignored` — it might be an unactioned
    human diagnosis (the shipped example: a real 1Password rate-limit root
    cause + two-line fix, never shipped). It must land in STATE_NOTE,
    produce zero Slack cards, and surface in the daily digest payload."""
    policy = dict(DEFAULT_POLICY, ignoreUnstructuredSlackProse=True)
    with _triage_env(policy=policy) as (conn, ctx):
        prose_title = ("1Password rate-limiting. Der Cronjob ruft `op run` jede Minute auf, "
                        "1.440 Authentifizierungen/Tag.")
        _insert_event(conn, source="slack_alert", external_id="op-rate-limit-note",
                       title=prose_title, first_seen=OLD)
        # Deliberately NOT starting with "sig-" — DEFAULT_POLICY's one rule
        # matches that prefix, and this row's job here is only to prove the
        # bracketed bot-alert shape survives the structural filter unmapped.
        _insert_event(conn, source="slack_alert", external_id="api-real-alert-down",
                       title="[API - HTTP] [:red_circle: Down] timeout <!channel>", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)

        states = {r["signature"]: r["state"] for r in
                  conn.execute("SELECT signature, state FROM triage_items").fetchall()}
        assert states["slack_alert:op-rate-limit-note"] == triage.STATE_NOTE, (
            "unstructured prose must land in STATE_NOTE, not STATE_IGNORED"
        )
        assert states["slack_alert:api-real-alert-down"] == triage.STATE_NEW

        assert calls == [], "a STATE_NOTE row must never escalate"
        # A genuine per-item card always has a `header` block (the item's
        # title); the digest post below does not — this distinguishes "a
        # card exists for the note" from "the note's text merely appears
        # inside the digest message", since both happen to contain the word
        # "1Password".
        card_posts = [
            p for p in ctx.posted
            if any(b.get("type") == "header" and "1Password" in b.get("text", {}).get("text", "")
                   for b in p["blocks"])
        ]
        assert card_posts == [], "a STATE_NOTE row must produce zero Slack cards"

        digest_posts = [p for p in ctx.posted if "Unstructured notes" in p["text"]]
        assert len(digest_posts) == 1, "the STATE_NOTE row must appear in the daily digest"
        digest_text = digest_posts[0]["text"]
        assert "slack_alert:op-rate-limit-note" in digest_text
        assert "1Password rate-limiting" in digest_text


def test_uk_maps_via_title_not_external_id():
    """The core fix for correction #1: uk's external_id is an opaque monitor
    id, unglobbable and unstable — only the title-derived match target makes
    it mappable."""
    policy = dict(DEFAULT_POLICY, rules=[{"match": "uk:macmini-dev-host-push", "repo": "dotfiles"}])
    with _triage_env(policy=policy) as (conn, ctx):
        eid = _insert_event(conn, source="uk", external_id="204", title="MacMini Dev Host - Push",
                             first_seen=OLD)
        triage.ingest(conn, NOW)
        triage.classify(conn, policy, NOW)
        item = triage._get_item(conn, eid)
        assert item["repo"] == "dotfiles", f"expected dotfiles via title match, got {item['repo']!r}"


def test_shipped_policy_routes_argo_infra_signals_to_vps():
    """Correction #4: an infra-signal alert about a RollHook-managed app
    maps to the repo owning its compose file/deploy target, not its source.
    argo is compose-managed inside `vps` (apps/argo/compose.yml, make
    argo-up) — a downed argo container, or its api-*/dashboard-* Kuma child
    monitors, must route to `vps`, never `argo`. Loads the REAL shipped
    config/triage-policy.json, not a test fixture, so a future accidental
    revert of this fix fails this test directly."""
    real_policy_path = REPO_ROOT / "config" / "triage-policy.json"
    real_policy = json.loads(real_policy_path.read_text())
    rules = real_policy["rules"]

    cases = [
        ("docker_vps:unhealthy:argo-web", "vps"),
        ("docker_vps:restart:argo-worker", "vps"),
        ("slack_alert:api-docker-red-circle-down-request-failed-with-status-code-404-channel", "vps"),
        ("slack_alert:api-http-red-circle-down-connect-ehostunreach-172-22-0-12-4000-channel", "vps"),
        ("slack_alert:dashboard-docker-red-circle-down-request-failed-with-status-code-404-channel", "vps"),
        ("slack_alert:dashboard-http-red-circle-down-connect-econnrefused-100-97-220-54-443-channel", "vps"),
    ]
    for target, expected_repo in cases:
        matched = None
        for rule in rules:
            import fnmatch as _fnmatch
            if _fnmatch.fnmatch(target, rule["match"]):
                matched = rule
                break
        assert matched is not None, f"{target!r} matched no rule in the shipped policy"
        assert matched.get("repo") == expected_repo, (
            f"{target!r} matched {matched!r}, expected repo={expected_repo!r}"
        )
    assert not any(r.get("repo") == "argo" for r in rules), (
        "no rule in the shipped policy may point at `argo` — the deploy target is `vps`"
    )


def test_max_open_investigations_cap():
    triage.MAX_OPEN_INVESTIGATIONS = 1
    with _triage_env() as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="sig-cap-a", title="A", first_seen=OLD)
        # A different repo so it does NOT cluster with sig-cap-a — this test
        # is about the concurrency cap across independent clusters.
        policy = dict(DEFAULT_POLICY, rules=[
            {"match": "slack_alert:sig-cap-a", "repo": "demo-repo"},
            {"match": "slack_alert:sig-cap-b", "repo": "other-repo"},
        ])
        _write_json(triage.POLICY_PATH, policy)
        _insert_event(conn, source="slack_alert", external_id="sig-cap-b", title="B", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        assert len(calls) == 1, f"MAX_OPEN_INVESTIGATIONS=1 must cap concurrent clusters, got {len(calls)}"
        states = [r["state"] for r in conn.execute("SELECT state FROM triage_items ORDER BY event_id").fetchall()]
        assert states.count(triage.STATE_INVESTIGATING) == 1
        assert states.count(triage.STATE_NEW) == 1


def test_daily_investigate_budget_cap():
    triage.DAILY_INVESTIGATE_BUDGET = 1
    with _triage_env() as (conn, ctx):
        policy = dict(DEFAULT_POLICY, rules=[
            {"match": "slack_alert:sig-budget-a", "repo": "demo-repo"},
            {"match": "slack_alert:sig-budget-b", "repo": "other-repo"},
        ])
        _write_json(triage.POLICY_PATH, policy)
        _insert_event(conn, source="slack_alert", external_id="sig-budget-a", title="A", first_seen=OLD)
        _insert_event(conn, source="slack_alert", external_id="sig-budget-b", title="B", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        assert len(calls) == 1, f"DAILY_INVESTIGATE_BUDGET=1 must cap dispatches, got {len(calls)}"


def test_denied_repo_never_dispatches():
    policy = dict(DEFAULT_POLICY, rules=[{"match": "slack_alert:sig-*", "repo": "denied-repo"}])
    with _triage_env(policy=policy, deny=["denied-repo"]) as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="sig-denied", title="Denied", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        assert calls == [], "a denied repo must never produce a dispatch"
        item = conn.execute("SELECT state, repo FROM triage_items").fetchone()
        assert item["repo"] == "denied-repo"
        assert item["state"] == triage.STATE_NEW
        assert ctx.total_calls() == 0


def test_unmapped_repo_never_dispatches():
    policy = dict(DEFAULT_POLICY, rules=[])
    with _triage_env(policy=policy) as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="sig-nowhere", title="Nowhere", first_seen=OLD)
        # Pre-seed today's unmapped-digest cursor so the separate, deliberate
        # digest mechanism doesn't count against "an unescalated item gets no card".
        today = NOW.date().isoformat()
        conn.execute("INSERT INTO cursors(key, value, updated_at) VALUES (?, ?, ?)",
                     (triage.DAILY_DIGEST_CURSOR_KEY, today, NOW.isoformat()))
        conn.commit()
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        assert calls == [], "an unmapped repo must never produce a dispatch"
        item = conn.execute("SELECT state, repo FROM triage_items").fetchone()
        assert item["repo"] is None
        assert item["state"] == triage.STATE_NEW
        assert ctx.total_calls() == 0, "an unescalated (state=new) item must never get a card"


def test_cluster_same_repo_one_dispatch_one_card_both_edges():
    with _triage_env() as (conn, ctx):
        e1 = _insert_event(conn, source="slack_alert", external_id="sig-cluster-a", title="A", first_seen=OLD)
        e2 = _insert_event(conn, source="slack_alert", external_id="sig-cluster-b", title="B", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)

        assert len(calls) == 1, f"two eligible items in the same repo must open exactly one dispatch, got {len(calls)}"
        assert len(ctx.posted) == 1, f"two eligible items in the same repo must produce exactly one card, got {len(ctx.posted)}"

        brief = calls[0]["brief"]
        assert "sig-cluster-a" in brief and "sig-cluster-b" in brief, "both signatures must be in the brief"

        for eid in (e1, e2):
            item = triage._get_item(conn, eid)
            assert item["state"] == triage.STATE_INVESTIGATING
            assert item["dispatch_job"] == "job-000001"
            event_row = triage._get_event(conn, eid)
            assert event_row["dispatch_id"] is not None, f"events.dispatch_id not written for member {eid}"


def test_cluster_different_repos_two_dispatches():
    policy = dict(DEFAULT_POLICY, rules=[
        {"match": "slack_alert:sig-diff-a", "repo": "demo-repo"},
        {"match": "slack_alert:sig-diff-b", "repo": "other-repo"},
    ])
    with _triage_env(policy=policy) as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="sig-diff-a", title="A", first_seen=OLD)
        _insert_event(conn, source="slack_alert", external_id="sig-diff-b", title="B", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        assert len(calls) == 2, f"two eligible items in different repos must open two dispatches, got {len(calls)}"
        assert len(ctx.posted) == 2


def test_cluster_dissolves_on_unrelated_verdict():
    with _triage_env() as (conn, ctx):
        e1 = _insert_event(conn, source="slack_alert", external_id="sig-split-a", title="A", first_seen=OLD)
        e2 = _insert_event(conn, source="slack_alert", external_id="sig-split-b", title="B", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        job_id = triage._get_item(conn, e1)["dispatch_job"]
        assert job_id is not None

        conn.execute(
            "UPDATE dispatches SET status=?, verdict_json=? WHERE job_id=?",
            ("done", json.dumps({"summary": "UNRELATED SIGNATURES — two separate causes.",
                                  "confidence": "high", "nextAction": "none"}), job_id),
        )
        conn.commit()
        triage.fold_dispatch_verdict(conn, origin_event_id=e1, job_id=job_id, now=NOW, dry_run=False)
        assert triage._get_item(conn, e1)["state"] == triage.STATE_VERDICT

        # A direct call, not triage.run(): run() would immediately re-cluster
        # the freshly-dissolved (now cooldown-unprotected-by-state-but-
        # dispatch_job-anchored) pair back together via escalate() in the
        # same pass — see _dissolve_cluster()'s own docstring. Dissolution
        # itself is what this test asserts, not the following escalation.
        triage.maybe_dissolve_clusters(conn, NOW, dry_run=False)
        for eid in (e1, e2):
            item = triage._get_item(conn, eid)
            assert item["state"] == triage.STATE_NEW, f"member {eid} should have been dissolved back to new"
            # dispatch_job is deliberately RETAINED as a cooldown anchor —
            # see _dissolve_cluster()'s docstring — not cleared.
            assert item["dispatch_job"] == job_id
            assert item["card_ts"] is None


def test_dispatch_brief_on_stdin_and_capped():
    """The one test exercising triage.py's REAL subprocess path (not the
    _fake_dispatcher fake) — a genuine stub script standing in for
    hermes-cc.sh, verifying the brief travels on stdin, never argv, and is
    capped at MAX_BRIEF_CHARS before it ever reaches the subprocess call."""
    with _triage_env() as (conn, ctx):
        huge_title = "A" * 9000
        eid = _insert_event(conn, source="slack_alert", external_id="sig-huge", title=huge_title, first_seen=OLD)

        tmp_dir = ctx.tmp_dir
        log_path = tmp_dir / "cc_calls.jsonl"
        stub_path = tmp_dir / "hermes-cc-stub.py"
        stub_path.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "argv = sys.argv[1:]\n"
            "stdin_text = sys.stdin.read()\n"
            f"with open({str(log_path)!r}, 'a') as f:\n"
            "    f.write(json.dumps({'argv': argv, 'stdin': stdin_text}) + chr(10))\n"
            "repo = argv[1] if len(argv) > 1 else '?'\n"
            "print(json.dumps({'verb': 'dispatch', 'ok': True, 'jobId': 'job-stdin-test', "
            "'repo': repo, 'tier': 'investigate', 'status': 'queued'}))\n"
        )
        stub_path.chmod(0o755)
        triage.HERMES_CC_BIN = stub_path

        triage.run(conn, dry_run=False)

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1, f"expected exactly one hermes-cc.sh invocation, got {len(lines)}"
        call = json.loads(lines[0])

        joined_argv = " ".join(call["argv"])
        assert "A" * 100 not in joined_argv, "the brief leaked into argv"
        assert "--brief" not in joined_argv

        assert len(call["stdin"]) <= triage.MAX_BRIEF_CHARS, (
            f"brief on stdin was {len(call['stdin'])} chars, over the {triage.MAX_BRIEF_CHARS} cap"
        )
        assert call["stdin"], "brief on stdin was empty"

        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_INVESTIGATING
        assert item["dispatch_job"] == "job-stdin-test"


def test_resolution_updates_card_once_then_stops():
    with _triage_env() as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="sig-resolve", title="Resolve me", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        calls_before = ctx.total_calls()
        assert calls_before >= 1

        conn.execute("UPDATE events SET resolved_at=? WHERE id=?", (NOW.isoformat(), eid))
        conn.commit()
        triage.run(conn, dry_run=False)
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_RESOLVED
        calls_after_resolve = ctx.total_calls()
        assert calls_after_resolve == calls_before + 1, "resolution must update the card exactly once"

        triage.run(conn, dry_run=False)
        assert ctx.total_calls() == calls_after_resolve, "a resolved card must stop being touched"


def test_dry_run_never_calls_slack_or_dispatch():
    with _triage_env() as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="sig-dry", title="Dry run", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=True)
        assert calls == [], "--dry-run must never shell out to hermes-cc.sh"
        assert ctx.total_calls() == 0, "--dry-run must never touch Slack"
        item = conn.execute("SELECT state, repo FROM triage_items").fetchone()
        assert item["repo"] == "demo-repo"
        assert item["state"] == triage.STATE_NEW


def test_dry_run_simulates_caps_across_repos():
    """escalate_cluster() always returns None under --dry-run (it never
    calls hermes-cc.sh) — the cap counters must still advance on the dry-run
    path (`or dry_run` in escalate()) so a --dry-run preview across several
    repos in one pass correctly shows a later repo deferred, matching what a
    real run would actually do."""
    triage.MAX_OPEN_INVESTIGATIONS = 1
    policy = dict(DEFAULT_POLICY, rules=[
        {"match": "slack_alert:sig-simA", "repo": "repo-a"},
        {"match": "slack_alert:sig-simB", "repo": "repo-b"},
    ])
    with _triage_env(policy=policy) as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="sig-simA", title="A", first_seen=OLD)
        _insert_event(conn, source="slack_alert", external_id="sig-simB", title="B", first_seen=OLD)
        import contextlib as _cl
        import io as _io
        out, err = _io.StringIO(), _io.StringIO()
        with _cl.redirect_stdout(out), _cl.redirect_stderr(err):
            triage.run(conn, dry_run=True)
        assert out.getvalue().count("would dispatch investigate") == 1, (
            f"expected exactly one simulated dispatch under the cap, got:\n{out.getvalue()}"
        )
        assert "MAX_OPEN_INVESTIGATIONS" in err.getvalue(), (
            f"expected the second repo's cluster to be deferred in the same dry-run pass:\n{err.getvalue()}"
        )
        # Nothing actually mutated.
        states = [r["state"] for r in conn.execute("SELECT state FROM triage_items").fetchall()]
        assert states == [triage.STATE_NEW, triage.STATE_NEW]


def test_reopen_after_resolve_preserves_artifact_url():
    """The exact scenario this file exists to fix: a signature that was
    investigated once (producing an artifact) recurs after being marked
    resolved — the prior artifact_url must survive the reopen so the next
    brief can say "a PR already exists"."""
    with _triage_env() as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="sig-recur", title="Recurring", first_seen=OLD)
        triage.ingest(conn, NOW)
        conn.execute(
            "UPDATE triage_items SET state=?, artifact_url=? WHERE event_id=?",
            (triage.STATE_RESOLVED, "https://github.com/jkrumm/demo-repo/pull/1", eid),
        )
        conn.commit()

        conn.execute("UPDATE events SET resolved_at=NULL WHERE id=?", (eid,))
        conn.commit()

        triage.reopen_if_needed(conn, NOW)
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_NEW
        assert item["artifact_url"] == "https://github.com/jkrumm/demo-repo/pull/1"


def test_fold_dispatch_verdict_pr_open():
    with _triage_env() as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="sig-verdict", title="Verdict test",
                             first_seen=OLD)
        triage.ingest(conn, NOW)
        job_id = "job-fold-1"
        conn.execute(
            "INSERT INTO dispatches(job_id,tier,repo,brief,why,origin_channel,origin_thread_ts,"
            "origin_event_id,status,verdict_json,artifact_url,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, "investigate", "demo-repo", "brief", None, "C0TESTCHAN01", "1000.000001", eid,
             "done", json.dumps({"summary": "Found it.", "confidence": "high", "nextAction": "review",
                                  "artifactUrl": "https://github.com/jkrumm/demo-repo/pull/2"}),
             "https://github.com/jkrumm/demo-repo/pull/2", NOW.isoformat()),
        )
        conn.commit()
        conn.execute(
            "UPDATE triage_items SET state=?, dispatch_job=?, card_channel=?, card_ts=? WHERE event_id=?",
            (triage.STATE_INVESTIGATING, job_id, "C0TESTCHAN01", "1000.000001", eid),
        )
        conn.commit()

        triage.fold_dispatch_verdict(conn, origin_event_id=eid, job_id=job_id, now=NOW, dry_run=False)
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_PR_OPEN
        assert item["artifact_url"] == "https://github.com/jkrumm/demo-repo/pull/2"
        assert len(ctx.updated) == 1, "fold_dispatch_verdict must sync the card immediately"


def test_fold_dispatch_verdict_updates_every_cluster_member():
    with _triage_env() as (conn, ctx):
        e1 = _insert_event(conn, source="slack_alert", external_id="sig-fm-a", title="A", first_seen=OLD)
        e2 = _insert_event(conn, source="slack_alert", external_id="sig-fm-b", title="B", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)
        job_id = triage._get_item(conn, e1)["dispatch_job"]

        conn.execute(
            "UPDATE dispatches SET status=?, verdict_json=?, artifact_url=? WHERE job_id=?",
            ("done", json.dumps({"summary": "Fixed both.", "confidence": "high",
                                  "artifactUrl": "https://github.com/jkrumm/demo-repo/pull/3"}),
             "https://github.com/jkrumm/demo-repo/pull/3", job_id),
        )
        conn.commit()
        triage.fold_dispatch_verdict(conn, origin_event_id=e1, job_id=job_id, now=NOW, dry_run=False)
        for eid in (e1, e2):
            item = triage._get_item(conn, eid)
            assert item["state"] == triage.STATE_PR_OPEN
            assert item["artifact_url"] == "https://github.com/jkrumm/demo-repo/pull/3"


def _write_env_check_stub(tmp_dir: Path, *, dangling_homelab: list[str] | None = None,
                           dangling_vps: list[str] | None = None) -> Path:
    """A stub standing in for hermes-ops.sh's `env-check --json`, returning
    exactly its documented shape."""
    stub_path = tmp_dir / "env-check-stub.py"
    payload = {
        "verb": "env-check", "ok": not (dangling_homelab or dangling_vps), "tier": "A",
        "homelab": {"ok": not dangling_homelab, "exitCode": 3 if dangling_homelab else 0,
                    "danglingItems": dangling_homelab or [], "error": None},
        "vps": {"ok": not dangling_vps, "exitCode": 3 if dangling_vps else 0,
                "danglingItems": dangling_vps or [], "error": None},
    }
    stub_path.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        f"print(json.dumps({payload!r}))\n"
    )
    stub_path.chmod(0o755)
    return stub_path


def test_op_refs_sources_are_ingested():
    """Correction #2: op_refs_homelab/op_refs_vps must not be structurally
    excluded from ingest — a dead 1Password ref must at minimum reach the
    daily digest even with no matching policy rule."""
    assert "op_refs_homelab" in triage.INGEST_SOURCES
    assert "op_refs_vps" in triage.INGEST_SOURCES
    with _triage_env(policy=dict(DEFAULT_POLICY, rules=[])) as (conn, ctx):
        eid = _insert_event(conn, source="op_refs_homelab", external_id="raw:some-error",
                             title="1Password refs unresolved on homelab", first_seen=OLD)
        triage.ingest(conn, NOW)
        item = triage._get_item(conn, eid)
        assert item is not None, "op_refs_homelab must produce a triage_items row"


def test_op_refs_route_to_env_check_verb_not_episode():
    """Correction #2: a dead 1Password ref must reach a deterministic VERB
    (hermes-ops.sh env-check), never a sideclaw episode — cheaper and safer
    (a bare item name in the output doesn't trip sideclaw's own secret-scan
    the way a dispatched verdict would)."""
    policy = dict(DEFAULT_POLICY, minOccurrences=1, minOpenMinutes=0,
                  rules=[{"match": "op_refs_homelab:*", "verb": "env-check"},
                         {"match": "op_refs_vps:*", "verb": "env-check"}])
    with _triage_env(policy=policy) as (conn, ctx):
        stub = _write_env_check_stub(ctx.tmp_dir, dangling_homelab=["gateway-secret"])
        triage.VERB_ALLOWLIST = {"env-check": [str(stub)]}

        eid = _insert_event(conn, source="op_refs_homelab", external_id="raw:some-error",
                             title="1Password refs unresolved on homelab", first_seen=OLD)
        calls: list[dict[str, Any]] = []
        triage._run_hermes_cc_dispatch = _fake_dispatcher(conn, calls)
        triage.run(conn, dry_run=False)

        assert calls == [], "a verb-routed item must never open a sideclaw episode"
        item = triage._get_item(conn, eid)
        assert item["repo"] is None
        assert item["verb"] == "env-check"
        assert item["state"] == triage.STATE_NEEDS_HUMAN
        assert "gateway-secret" in item["note"]
        assert "make secrets-seed" in item["note"]
        assert item["dispatch_job"] is None

        event_row = triage._get_event(conn, eid)
        assert event_row["dispatch_id"] is None, "a verb outcome never touches the dispatch bridge"

        # The card carries the dangling item + remediation inline.
        assert len(ctx.posted) == 1
        blocks_text = json.dumps(ctx.posted[0]["blocks"])
        assert "gateway-secret" in blocks_text
        assert "make secrets-seed" in blocks_text


def test_op_refs_no_dangling_item_still_reaches_needs_human():
    policy = dict(DEFAULT_POLICY, minOccurrences=1, minOpenMinutes=0,
                  rules=[{"match": "op_refs_vps:*", "verb": "env-check"}])
    with _triage_env(policy=policy) as (conn, ctx):
        stub = _write_env_check_stub(ctx.tmp_dir)  # nothing dangling — ok: true
        triage.VERB_ALLOWLIST = {"env-check": [str(stub)]}
        eid = _insert_event(conn, source="op_refs_vps", external_id="some-item", title="unresolved",
                             first_seen=OLD)
        triage.run(conn, dry_run=False)
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_NEEDS_HUMAN
        assert "no dangling item" in item["note"]


def test_op_refs_raw_fallback_dedups_across_timestamps():
    """Correction #3: watchdog-poll.py's `raw:` op-refs fallback signature
    must not embed a timestamp — two stderr strings differing ONLY in their
    timestamp must produce the SAME external_id, or every 30-min poll mints
    a fresh row and the dangling ref never stays flagged."""
    s1 = "[ERROR] 2026/09/01 15:00:34 (504) Unknown: An unknown error occurred."
    s2 = "[ERROR] 2026/09/02 03:11:09 (504) Unknown: An unknown error occurred."
    key1 = watchdog_poll.normalize_title(watchdog_poll._strip_op_refs_timestamps(s1))[:80]
    key2 = watchdog_poll.normalize_title(watchdog_poll._strip_op_refs_timestamps(s2))[:80]
    assert key1 == key2, f"timestamps must not survive into the dedup key: {key1!r} != {key2!r}"
    assert "2026" not in key1 and "01" not in key1.split("-")

    # A dash-separated ISO shape (the form the OLD, buggy key itself used to
    # normalize into) must also collapse identically.
    s3 = "op run failed: timeout at 2026-09-01T15:00:34.504Z during resolve"
    s4 = "op run failed: timeout at 2026-09-02T03:11:09.118Z during resolve"
    key3 = watchdog_poll.normalize_title(watchdog_poll._strip_op_refs_timestamps(s3))[:80]
    key4 = watchdog_poll.normalize_title(watchdog_poll._strip_op_refs_timestamps(s4))[:80]
    assert key3 == key4


def test_unknown_verb_key_is_rejected_at_policy_load():
    """A policy rule must never be able to name an arbitrary command — only
    a key in the code-side VERB_ALLOWLIST is accepted."""
    policy = dict(DEFAULT_POLICY, rules=[{"match": "op_refs_homelab:*", "verb": "rm-rf-everything"}])
    with _triage_env(policy=policy) as (conn, ctx):
        loaded = triage.load_policy()
        assert loaded["rules"] == [], "an unknown verb key must be dropped, not passed through"


# --- runner ------------------------------------------------------------------

def main() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items())
              if name.startswith("test_") and callable(fn)]
    passed = 0
    failures: list[str] = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            failures.append(f"{name}: {e}")
        except Exception:
            failures.append(f"{name}: unexpected exception\n{traceback.format_exc()}")

    print(f"{passed}/{len(tests)} passed")
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
