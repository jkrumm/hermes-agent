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
import time
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import traceback
import types
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
        "_run_hermes_cc_auto_implement": triage._run_hermes_cc_auto_implement,
        "_run_hermes_cc_validation": triage._run_hermes_cc_validation,
        "_run_hermes_cc_merge": triage._run_hermes_cc_merge,
        "_hermes_cc_status": triage._hermes_cc_status,
        "LIVENESS_ALLOWLIST": dict(triage.LIVENESS_ALLOWLIST),
        "MAX_OPEN_INVESTIGATIONS": triage.MAX_OPEN_INVESTIGATIONS,
        "DAILY_INVESTIGATE_BUDGET": triage.DAILY_INVESTIGATE_BUDGET,
        "VERB_ALLOWLIST": dict(triage.VERB_ALLOWLIST),
        "_watchdog_poll": triage._watchdog_poll,
        "METEO_HEALTH_PATH": triage.METEO_HEALTH_PATH,
        "GATEWAY_STARTS_LOG": triage.GATEWAY_STARTS_LOG,
        "HERMES_ERROR_LOG": triage.HERMES_ERROR_LOG,
        "TRIAGE_REPO_DIR": triage.TRIAGE_REPO_DIR,
        "_call_propose_mappings_model": triage._call_propose_mappings_model,
        "_resolve_openai_base_url": triage._resolve_openai_base_url,
        "_resolve_openai_api_key": triage._resolve_openai_api_key,
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
VERY_OLD = NOW - dt.timedelta(days=10)


def _init_policy_git_repo(tmp_dir: Path, policy_data: dict[str, Any]) -> Path:
    """Sets up a throwaway git checkout shaped like this repo's own
    (`config/triage-policy.json` under a repo root, one clean initial
    commit) and points triage.TRIAGE_REPO_DIR / triage.POLICY_PATH at it —
    the fixture propose_mappings()'s git-commit path needs, since it always
    resolves POLICY_PATH relative to TRIAGE_REPO_DIR before ever touching
    git. Caller must be inside a `with _triage_env()` block (or otherwise
    responsible for restoring these two module globals) — _triage_env's own
    `saved` dict already covers TRIAGE_REPO_DIR."""
    repo_dir = tmp_dir / "policy-repo"
    (repo_dir / "config").mkdir(parents=True)
    policy_path = repo_dir / "config" / "triage-policy.json"
    policy_path.write_text(triage._dump_policy_json(policy_data))
    subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "initial"], check=True)
    triage.TRIAGE_REPO_DIR = repo_dir
    triage.POLICY_PATH = policy_path
    return repo_dir


def _setup_discoverable_repos(ctx, names: list[str], *, deny: list[str] | None = None) -> Path:
    """Points triage.DISPATCH_REPOS_JSON at a throwaway `root` containing one
    fake `.git` checkout per name in `names` — the hermetic equivalent of
    hermes-cc.sh's own discoverable() step, so propose_mappings() tests never
    depend on this dev machine's real ~/SourceRoot layout."""
    root_dir = ctx.tmp_dir / "fake-source-root"
    for n in names:
        (root_dir / n / ".git").mkdir(parents=True)
    _write_json(triage.DISPATCH_REPOS_JSON, {"root": str(root_dir), "deny": deny or []})
    return root_dir


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


# --- evidence commands (declared runtime-state probes) -----------------------

def _fake_wp_module(messages=None, *, homelab_key: str = "test-homelab-key", fetch_ok: bool = True):
    """A stand-in for the watchdog-poll.py sibling module used by
    _gather_kuma_push_last()/resolve_recovery_paired() — no real network call,
    no dependency on a real HOMELAB_API_KEY being resolvable in this venv."""
    return types.SimpleNamespace(
        resolve_secret=lambda key: homelab_key if key == "HOMELAB_API_KEY" else "",
        poll_slack_messages=lambda env, channel_id, since_ts, skip_uk_push=False: (
            list(messages or []), None, fetch_ok
        ),
    )


def _slack_msg(ts: str, text: str) -> dict[str, Any]:
    return {"external_id": ts, "title": text[:240], "url": "", "payload": {"text": text}}


def test_evidence_meteo_health_bounded_output():
    """meteo-health must summarize (not dump) var/health.json, and the
    rendered evidence block must stay bounded even when the source file is
    large — ~40 real checks, several failing, well over EVIDENCE_CAP_CHARS
    once rendered raw."""
    with _triage_env() as (conn, ctx):
        health_path = ctx.tmp_dir / "meteo-health.json"
        checks = [{"name": f"check-{i}", "ok": False, "detail": "x" * 200} for i in range(40)]
        _write_json(health_path, {"ok": False, "heartbeat": "skipped(failure)",
                                   "timestamp": "2026-09-08T18:47:52+00:00", "checks": checks})
        triage.METEO_HEALTH_PATH = health_path

        raw = triage._gather_evidence("meteo-health", [])
        assert "ok=False" in raw and "40/40 checks failing" in raw

        block = triage._build_evidence_block(["meteo-health"], {1: None}, triage.EVIDENCE_TOTAL_CAP_CHARS)
        assert "meteo-health" in block
        assert len(block) <= triage.EVIDENCE_TOTAL_CAP_CHARS
        assert "…" in block, "a 40-check dump must have been truncated by the per-key cap"


def test_evidence_gateway_starts_bounded_output():
    with _triage_env() as (conn, ctx):
        starts_path = ctx.tmp_dir / "gateway-starts.log"
        base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp()
        starts_path.write_text("\n".join(str(base + i * 3600) for i in range(20)) + "\n")
        triage.GATEWAY_STARTS_LOG = starts_path

        result = triage._gather_evidence("gateway-starts", [])
        assert "last 5 gateway start(s)" in result
        assert result.count(" UTC") == 5, "must show the 5 most recent starts, not every one on file"
        assert "2026-01-01 00:00" not in result, "must show the 5 MOST RECENT starts, not the earliest ones"
        assert len(result) <= triage.EVIDENCE_CAP_CHARS


def test_evidence_hermes_log_tail_slices_at_gateway_start():
    """The fix skills/hermes-gateway/SKILL.md's Rule 0 documents: a raw tail
    mixes a dead incarnation's errors with the live one. gateway-starts.log's
    last entry is the boundary; nothing before it may appear in the result."""
    with _triage_env() as (conn, ctx):
        boundary_dt = dt.datetime(2026, 1, 1, 12, 0, 0)
        starts_path = ctx.tmp_dir / "gateway-starts.log"
        starts_path.write_text(f"{boundary_dt.timestamp()}\n")
        triage.GATEWAY_STARTS_LOG = starts_path

        error_log = ctx.tmp_dir / "errors.log"
        error_log.write_text(
            "2026-01-01 11:59:00,000 WARNING old.module: BEFORE_BOUNDARY_MUST_BE_EXCLUDED\n"
            "2026-01-01 12:00:00,000 WARNING new.module: AT_BOUNDARY_MUST_BE_INCLUDED\n"
            "2026-01-01 12:00:05,000 WARNING new.module: AFTER_BOUNDARY_MUST_BE_INCLUDED\n"
        )
        triage.HERMES_ERROR_LOG = error_log

        result = triage._gather_evidence("hermes-log-tail", [])
        assert "BEFORE_BOUNDARY_MUST_BE_EXCLUDED" not in result
        assert "AT_BOUNDARY_MUST_BE_INCLUDED" in result
        assert "AFTER_BOUNDARY_MUST_BE_INCLUDED" in result
        assert "sliced at current gateway start" in result


def test_evidence_kuma_push_last_matches_bracket_and_normalizes():
    with _triage_env() as (conn, ctx):
        eid = _insert_event(conn, source="uk", external_id="204", title="MacMini Dev Host - Push",
                             first_seen=OLD)
        uk_event = triage._get_event(conn, eid)

        older = "[MacMini Dev Host - Push] all green"
        newest = "[MacMini Dev Host - Push] FAIL: disk 90% used (max 90%)"
        unrelated = "[Some Other Monitor - Push] unrelated"
        triage._watchdog_poll = _fake_wp_module([
            _slack_msg("100.000001", older),
            _slack_msg("300.000001", newest),
            _slack_msg("200.000001", unrelated),
        ])

        result = triage._gather_evidence("kuma-push-last", [uk_event])
        assert result == newest, "must pick the CHRONOLOGICALLY LATEST match, not list order"
        assert "Some Other Monitor" not in result


def test_evidence_kuma_push_last_no_uk_member_is_non_fatal():
    with _triage_env() as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="sig-a", title="not a uk event",
                             first_seen=OLD)
        event_row = triage._get_event(conn, eid)
        triage._watchdog_poll = _fake_wp_module([])
        result = triage._gather_evidence("kuma-push-last", [event_row])
        assert "no uk" in result.lower()


def test_evidence_hang_does_not_block_past_its_timeout():
    """_run_bounded() must RETURN at its timeout, not merely report one.

    Regression test for a real bug: the executor was used as a context manager,
    whose __exit__ calls shutdown(wait=True) and blocks until the worker thread
    finishes. A hung gatherer (a stuck network read, an unresponsive mount) would
    therefore sail past `timeout` and stall the whole 10-minute loop, while the
    caller still saw a tidy "timed out" string. The bug was invisible to every
    other evidence test, because a gatherer that raises or returns quickly exits
    the `with` block immediately either way — only an actual hang exposes it.
    Asserts wall-clock, which is the only thing that would have caught it."""
    started = time.monotonic()
    ok, result = triage._run_bounded(lambda: time.sleep(20), timeout=1)
    elapsed = time.monotonic() - started
    assert ok is False, ok
    assert "timed out" in result, result
    assert elapsed < 5, f"_run_bounded blocked {elapsed:.1f}s past a 1s timeout"


def test_evidence_command_failure_is_non_fatal():
    """A raising gatherer must never abort the run — _run_bounded() folds it
    into an error string, and _build_evidence_block() still renders every
    OTHER requested key normally alongside it."""
    with _triage_env() as (conn, ctx):
        starts_path = ctx.tmp_dir / "gateway-starts.log"
        starts_path.write_text(f"{dt.datetime.now(dt.timezone.utc).timestamp()}\n")
        triage.GATEWAY_STARTS_LOG = starts_path

        saved_gatherers = dict(triage._EVIDENCE_GATHERERS)
        try:
            def _boom(_event_rows):
                raise RuntimeError("simulated evidence failure")

            triage._EVIDENCE_GATHERERS = {**saved_gatherers, "meteo-health": _boom}

            single = triage._gather_evidence("meteo-health", [])
            assert "evidence command 'meteo-health' failed" in single
            assert "simulated evidence failure" in single

            block = triage._build_evidence_block(["meteo-health", "gateway-starts"], {1: None},
                                                   triage.EVIDENCE_TOTAL_CAP_CHARS)
            assert "meteo-health" in block and "gateway-starts" in block
            assert "simulated evidence failure" in block
            assert "gateway start" in block, "a failing key must not take down a sibling key's output"
        finally:
            triage._EVIDENCE_GATHERERS = saved_gatherers


def test_unknown_evidence_key_rejected_at_policy_load():
    """Same closed-set contract as verbs — a policy file must never be able
    to name anything outside EVIDENCE_ALLOWLIST."""
    policy = dict(DEFAULT_POLICY, rules=[{"match": "slack_alert:sig-*", "repo": "demo-repo",
                                           "evidence": ["not-a-real-key"]}])
    with _triage_env(policy=policy) as (conn, ctx):
        loaded = triage.load_policy()
        assert loaded["rules"] == [], "an unknown evidence key must drop the whole rule, not pass it through"


def test_evidence_total_stays_under_brief_cap():
    """A cluster whose title is already huge leaves little budget for
    evidence — the whole brief (structure + evidence) must still respect
    MAX_BRIEF_CHARS, the evidence block must be what gets cut, never the
    closing instructions, and a truncation note must say so."""
    policy = dict(DEFAULT_POLICY, rules=[
        {"match": "slack_alert:sig-*", "repo": "demo-repo",
         "evidence": ["meteo-health", "gateway-starts", "hermes-log-tail", "kuma-push-last"]},
    ])
    with _triage_env(policy=policy) as (conn, ctx):
        health_path = ctx.tmp_dir / "meteo-health.json"
        checks = [{"name": f"check-{i}", "ok": False, "detail": "y" * 200} for i in range(40)]
        _write_json(health_path, {"ok": False, "heartbeat": "skipped(failure)",
                                   "timestamp": "2026-09-08T00:00:00+00:00", "checks": checks})
        triage.METEO_HEALTH_PATH = health_path
        triage.GATEWAY_STARTS_LOG = ctx.tmp_dir / "does-not-exist.log"
        triage.HERMES_ERROR_LOG = ctx.tmp_dir / "does-not-exist-errors.log"
        triage._watchdog_poll = _fake_wp_module([])

        # Large enough to leave a tight-but-positive evidence budget once the
        # brief's own structure (the title appears twice: once in the alert
        # line, once as its own "raw:" echo) is accounted for — see
        # _build_cluster_brief()'s own evidence-budget comment. A title big
        # enough to ALSO blow the structure itself is a different, pre-
        # existing case (see test_dispatch_brief_on_stdin_and_capped) and
        # would not isolate what this test is checking.
        huge_title = "A" * 3000
        _insert_event(conn, source="slack_alert", external_id="sig-huge-evidence", title=huge_title,
                       first_seen=OLD)

        stub_path = ctx.tmp_dir / "hermes-cc-stub.py"
        log_path = ctx.tmp_dir / "cc_calls.jsonl"
        stub_path.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "argv = sys.argv[1:]\n"
            "stdin_text = sys.stdin.read()\n"
            f"with open({str(log_path)!r}, 'a') as f:\n"
            "    f.write(json.dumps({'stdin': stdin_text}) + chr(10))\n"
            "repo = argv[1] if len(argv) > 1 else '?'\n"
            "print(json.dumps({'verb': 'dispatch', 'ok': True, 'jobId': 'job-evidence-cap-test', "
            "'repo': repo, 'tier': 'investigate', 'status': 'queued'}))\n"
        )
        stub_path.chmod(0o755)
        triage.HERMES_CC_BIN = stub_path

        triage.run(conn, dry_run=False)

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1
        brief = json.loads(lines[0])["stdin"]

        assert len(brief) <= triage.MAX_BRIEF_CHARS, (
            f"brief was {len(brief)} chars, over the {triage.MAX_BRIEF_CHARS} cap"
        )
        assert "This alert reached the auto-triage escalation threshold" in brief, (
            "the brief's own closing structure must survive intact — only evidence gets cut"
        )
        assert "CAPTURED RUNTIME STATE" in brief
        assert "truncated to fit the brief cap" in brief, "a 40-check dump plus a 7000-char title must force evidence truncation"


# --- grouped-source resolution (quiet timer + recovery pairing) --------------

def test_quiet_grouped_resolves_after_window_and_updates_card_once():
    """A CARDED item (card_ts already set, as a real escalation would leave
    it) still gets its final chat.update on a quiet-timer resolve — the
    positive half of the 2026-09-08 correction, see
    test_new_to_resolved_with_no_card_is_silent for the negative half."""
    policy = dict(DEFAULT_POLICY, quietResolveHours=1)
    with _triage_env(policy=policy) as (conn, ctx):
        triage._watchdog_poll = _fake_wp_module([], homelab_key="")  # no token -> pairing path is a no-op
        quiet_first_seen = NOW - dt.timedelta(hours=5)
        eid = _insert_event(conn, source="slack_alert", external_id="sig-quiet", title="🚨 quiet thing",
                             first_seen=quiet_first_seen)
        stale_anchor = (NOW - dt.timedelta(hours=3)).isoformat()
        conn.execute("UPDATE events SET notified_at=?, last_reminder_at=? WHERE id=?",
                     (stale_anchor, stale_anchor, eid))
        conn.execute(
            "INSERT INTO triage_items(event_id, signature, repo, state, occurrences, first_seen, "
            "last_seen, created_at, updated_at, card_channel, card_ts, card_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, "slack_alert:sig-quiet", "demo-repo", triage.STATE_VERDICT, 5,
             quiet_first_seen.isoformat(), stale_anchor, NOW.isoformat(), NOW.isoformat(),
             "C0TESTCHAN01", "1000.000001", "stale-hash-from-a-prior-post"),
        )
        conn.commit()

        triage.run(conn, dry_run=False)
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_RESOLVED
        assert item["note"].startswith(triage.QUIET_RESOLVE_NOTE_PREFIX)
        assert "fixed" not in item["note"].lower()
        assert len(ctx.updated) == 1 and len(ctx.posted) == 0, (
            f"an already-carded item's resolve must be exactly one chat.update, never a "
            f"chat.postMessage — got {len(ctx.updated)} update(s), {len(ctx.posted)} post(s)")
        calls_after_first = ctx.total_calls()

        triage.run(conn, dry_run=False)
        # NOTE: this passes only because the re-rendered card is byte-identical, so
        # card_hash short-circuits it — NOT because the item stops churning. It is
        # reopened by reopen_if_needed() every run (a grouped event's resolved_at
        # stays NULL for months) and quiet-resolved again immediately. Any change
        # that varies the resolve note by even one character turns that invisible
        # churn into a chat.update every ten minutes. See docs/triage.md
        # §Known: grouped reopen churn.
        assert ctx.total_calls() == calls_after_first, (
            f"a resolved card must update exactly once — got "
            f"{ctx.total_calls() - calls_after_first} extra call(s) on the second run")


def test_new_to_resolved_with_no_card_is_silent():
    """The 2026-09-08 correction, negative half: an item whose whole life is
    `new -> resolved` — never escalated, never carded — must announce
    NOTHING. This is the exact shape of the 13-card burst: apply_resolutions()
    flips a `new` row straight to `resolved` the moment its underlying event
    resolves, with no card_ts ever having been set."""
    # Mapped (so it never becomes an "unmapped" digest entry either — this
    # test is about the CARD, not the digest) but held below minOccurrences/
    # minOpenMinutes forever, so it stays `new` through the first pass.
    policy = dict(DEFAULT_POLICY, minOccurrences=999, minOpenMinutes=999999)
    with _triage_env(policy=policy) as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="sig-never-carded",
                             title="Never carded", first_seen=OLD)
        triage.run(conn, dry_run=False)  # ingest + classify only — the event is still open
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_NEW and item["card_ts"] is None
        assert ctx.total_calls() == 0, "an unescalated `new` item must never get a card"

        conn.execute("UPDATE events SET resolved_at=? WHERE id=?", (NOW.isoformat(), eid))
        conn.commit()
        triage.run(conn, dry_run=False)

        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_RESOLVED
        assert item["card_ts"] is None
        assert ctx.total_calls() == 0, "new -> resolved with no prior card must make zero Slack calls"


def test_investigating_to_resolved_updates_card_exactly_once():
    """The narrower, exact-shape sibling of the quiet-timer test above: an
    ordinary event-driven resolve (apply_resolutions(), not the quiet timer)
    on an already-carded `investigating` item is exactly one chat.update and
    zero chat.postMessage."""
    with _triage_env() as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="sig-inv-resolve",
                             title="🚨 in flight", first_seen=OLD)
        conn.execute(
            "INSERT INTO triage_items(event_id, signature, repo, state, occurrences, first_seen, "
            "last_seen, created_at, updated_at, dispatch_job, card_channel, card_ts, card_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, "slack_alert:sig-inv-resolve", "demo-repo", triage.STATE_INVESTIGATING, 3,
             OLD.isoformat(), OLD.isoformat(), NOW.isoformat(), NOW.isoformat(),
             "job-in-flight", "C0TESTCHAN01", "1000.000002", "stale-hash-from-a-prior-post"),
        )
        conn.commit()

        conn.execute("UPDATE events SET resolved_at=? WHERE id=?", (NOW.isoformat(), eid))
        conn.commit()
        triage.run(conn, dry_run=False)

        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_RESOLVED
        assert len(ctx.updated) == 1 and len(ctx.posted) == 0, (
            "investigating -> resolved on an already-carded item must be exactly one "
            f"chat.update and zero chat.postMessage, got updated={len(ctx.updated)} posted={len(ctx.posted)}"
        )


def test_quiet_grouped_does_not_resolve_while_investigating():
    """An open dispatch (state=investigating) must never be yanked to
    resolved by the quiet timer — let the investigation finish first."""
    policy = dict(DEFAULT_POLICY, quietResolveHours=1)
    with _triage_env(policy=policy) as (conn, ctx):
        triage._watchdog_poll = _fake_wp_module([], homelab_key="")
        first_seen = NOW - dt.timedelta(hours=5)
        eid = _insert_event(conn, source="slack_alert", external_id="sig-inflight", title="🚨 in flight",
                             first_seen=first_seen)
        stale_anchor = (NOW - dt.timedelta(hours=3)).isoformat()
        conn.execute("UPDATE events SET notified_at=?, last_reminder_at=? WHERE id=?",
                     (stale_anchor, stale_anchor, eid))
        conn.execute(
            "INSERT INTO triage_items(event_id, signature, repo, state, dispatch_job, occurrences, "
            "first_seen, last_seen, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (eid, "slack_alert:sig-inflight", "demo-repo", triage.STATE_INVESTIGATING, "job-inflight", 5,
             first_seen.isoformat(), stale_anchor, NOW.isoformat(), NOW.isoformat()),
        )
        conn.commit()
        triage.resolve_quiet_grouped(conn, policy, NOW)
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_INVESTIGATING, "must not resolve out from under an open dispatch"


def test_recovery_paired_resolves_immediately_without_waiting_for_quiet():
    """The exact scenario the brief shipped this for: research-gateway
    job.reaped fixed and deployed, HyperDX posts a ✅ recovery message —
    this must resolve on the VERY NEXT run, not wait out quietResolveHours."""
    policy = dict(DEFAULT_POLICY, quietResolveHours=999)
    with _triage_env(policy=policy) as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="research-gateway-job-reaped-1-15m",
                             title="🚨 research-gateway job.reaped >= 1 (15m) (×3 in batch)", first_seen=OLD)
        conn.execute(
            "INSERT INTO triage_items(event_id, signature, repo, state, occurrences, first_seen, "
            "last_seen, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (eid, "slack_alert:research-gateway-job-reaped-1-15m", "vps", triage.STATE_NEEDS_HUMAN, 3,
             OLD.isoformat(), NOW.isoformat(), NOW.isoformat(), NOW.isoformat()),
        )
        conn.commit()

        recovery_text = "✅ research-gateway job.reaped >= 1 (15m)"
        triage._watchdog_poll = _fake_wp_module([_slack_msg("999.000001", recovery_text)])

        triage.run(conn, dry_run=False)
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_RESOLVED
        assert item["note"].startswith(triage.RECOVERY_PAIRED_NOTE_PREFIX)
        assert recovery_text in item["note"]
        assert "fixed" not in item["note"].lower()


def test_recovery_pairing_skipped_under_dry_run():
    """--dry-run must make zero outbound calls, Slack reads included — a
    preview against a throwaway DB copy must never depend on live
    credentials or network."""
    policy = dict(DEFAULT_POLICY, quietResolveHours=999)
    with _triage_env(policy=policy) as (conn, ctx):
        calls = {"n": 0}

        def _counting_poll(env, channel_id, since_ts, skip_uk_push=False):
            calls["n"] += 1
            return [], None, True

        triage._watchdog_poll = types.SimpleNamespace(
            resolve_secret=lambda key: "test-key", poll_slack_messages=_counting_poll,
        )
        _insert_event(conn, source="slack_alert", external_id="sig-dryrun-pair", title="🚨 dry run pairing",
                       first_seen=OLD)
        triage.run(conn, dry_run=True)
        assert calls["n"] == 0, "resolve_recovery_paired must never fetch Slack under --dry-run"


# =============================================================================
# The auto-implement chain (steps 6-10) — verdict -> implement -> validate ->
# merge -> deploy -> verify. hermes-cc.sh itself is stubbed at the Python
# function boundary (triage._run_hermes_cc_auto_implement / _validation /
# _merge / _hermes_cc_status), the same shape _fake_dispatcher already uses
# for triage._run_hermes_cc_dispatch above — these are the only four points
# this file ever crosses into a subprocess for this chain.
# =============================================================================

def _seed_verdict_item(conn, *, event_id_source="slack_alert", external_id="sig-verdict",
                        repo="demo-repo", next_action="implement", confidence="high",
                        investigate_job="investigate-job") -> int:
    eid = _insert_event(conn, source=event_id_source, external_id=external_id, title="Verdict item",
                         first_seen=OLD)
    conn.execute(
        "INSERT INTO dispatches(job_id,tier,repo,brief,status,verdict_json,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (investigate_job, "investigate", repo, "b", "done",
         json.dumps({"summary": "s", "nextAction": next_action, "confidence": confidence}),
         NOW.isoformat()),
    )
    conn.execute(
        "INSERT INTO triage_items(event_id, signature, repo, state, occurrences, first_seen, "
        "last_seen, created_at, updated_at, dispatch_job) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (eid, f"{event_id_source}:{external_id}", repo, triage.STATE_VERDICT, 3,
         OLD.isoformat(), OLD.isoformat(), NOW.isoformat(), NOW.isoformat(), investigate_job),
    )
    conn.commit()
    return eid


def _seed_implement_dispatch(conn, job_id: str, *, repo="demo-repo") -> None:
    conn.execute(
        "INSERT INTO dispatches(job_id,tier,repo,brief,status,created_at) VALUES(?,?,?,?,?,?)",
        (job_id, "implement", repo, "b", "done", NOW.isoformat()),
    )
    conn.commit()


def test_auto_implement_fires_only_at_high_confidence():
    with _triage_env() as (conn, ctx):
        eid_hi = _seed_verdict_item(conn, external_id="sig-hi", confidence="high",
                                     investigate_job="investigate-hi")
        eid_med = _seed_verdict_item(conn, external_id="sig-med", confidence="medium",
                                      investigate_job="investigate-med")

        calls: list[tuple[str, int]] = []

        def _fake_auto_implement(*, repo, event_id):
            calls.append((repo, event_id))
            return "implement-job-001"

        triage._run_hermes_cc_auto_implement = _fake_auto_implement
        triage.maybe_auto_implement(conn, DEFAULT_POLICY, NOW, dry_run=False)

        assert calls == [("demo-repo", eid_hi)], f"expected exactly the high-confidence item, got {calls}"
        item_hi = triage._get_item(conn, eid_hi)
        assert item_hi["state"] == triage.STATE_IMPLEMENTING
        assert item_hi["implement_job"] == "implement-job-001"
        item_med = triage._get_item(conn, eid_med)
        assert item_med["state"] == triage.STATE_VERDICT, "a medium-confidence verdict must never auto-implement"


def test_auto_implement_claims_the_item_before_dispatching():
    """The claim must be written BEFORE hermes-cc.sh is called, not after.

    Eligibility is `state='verdict' AND implement_job IS NULL`. If the claim were
    recorded only after the dispatch returned, a crash in that window would leave the
    item eligible again on the next tick and open a SECOND implement episode for the
    same verdict — duplicate branches and duplicate draft PRs. Asserts the state the
    dispatcher observes while it runs, which is the only way to see the ordering.
    Also asserts the claim is handed back when the dispatch refuses, so a failed
    dispatch cannot strand an item in `implementing` with no job to poll."""
    with _triage_env() as (conn, ctx):
        eid = _seed_verdict_item(conn, external_id="sig-claim", confidence="high",
                                 investigate_job="investigate-claim")
        observed: list[str] = []

        def _observing_dispatch(*, repo, event_id):
            observed.append(triage._get_item(conn, event_id)["state"])
            return "implement-job-claim"

        triage._run_hermes_cc_auto_implement = _observing_dispatch
        triage.maybe_auto_implement(conn, DEFAULT_POLICY, NOW, dry_run=False)
        assert observed == [triage.STATE_IMPLEMENTING], (
            f"item must already be claimed while the dispatch runs, saw {observed}")

        # A refused dispatch hands the claim back.
        eid2 = _seed_verdict_item(conn, external_id="sig-claim-fail", confidence="high",
                                  investigate_job="investigate-claim-fail")
        triage._run_hermes_cc_auto_implement = lambda *, repo, event_id: None
        triage.maybe_auto_implement(conn, DEFAULT_POLICY, NOW, dry_run=False)
        back = triage._get_item(conn, eid2)
        assert back["state"] == triage.STATE_VERDICT, back["state"]
        assert back["implement_job"] is None, back["implement_job"]


def test_implement_success_opens_validation_on_a_different_model():
    with _triage_env() as (conn, ctx):
        eid = _seed_verdict_item(conn, external_id="sig-impl-ok")
        conn.execute(
            "UPDATE triage_items SET state=?, implement_job=? WHERE event_id=?",
            (triage.STATE_IMPLEMENTING, "implement-job-002", eid),
        )
        conn.commit()

        triage._hermes_cc_status = lambda job_id: {
            "ok": True, "status": "done", "artifactUrl": "https://github.com/jkrumm/demo-repo/pull/9",
        }
        validation_calls = []

        def _fake_validation(conn_arg, *, repo, event_id, implement_job, pr_url):
            validation_calls.append((repo, event_id, implement_job, pr_url))
            return "validation-job-001"

        triage._run_hermes_cc_validation = _fake_validation
        triage.poll_implement_jobs(conn, DEFAULT_POLICY, NOW, dry_run=False)

        assert validation_calls == [("demo-repo", eid, "implement-job-002",
                                     "https://github.com/jkrumm/demo-repo/pull/9")]
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_VALIDATING
        assert item["validation_job"] == "validation-job-001"
        assert item["pr_url"] == "https://github.com/jkrumm/demo-repo/pull/9"


def test_implement_failure_blocks_without_opening_validation():
    with _triage_env() as (conn, ctx):
        eid = _seed_verdict_item(conn, external_id="sig-impl-fail")
        conn.execute(
            "UPDATE triage_items SET state=?, implement_job=? WHERE event_id=?",
            (triage.STATE_IMPLEMENTING, "implement-job-003", eid),
        )
        conn.commit()

        triage._hermes_cc_status = lambda job_id: {"ok": False, "status": "failed", "error": "budget exhausted"}
        validation_calls = []
        triage._run_hermes_cc_validation = lambda *a, **kw: validation_calls.append(1) or "should-not-run"

        triage.poll_implement_jobs(conn, DEFAULT_POLICY, NOW, dry_run=False)

        assert validation_calls == []
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_MERGE_BLOCKED
        assert "failed" in item["note"]


def test_disagreeing_validation_blocks_the_merge():
    """A validation verdict that disagrees blocks the merge and puts the
    disagreement on the card — `merge` must never even be called."""
    with _triage_env() as (conn, ctx):
        eid = _seed_verdict_item(conn, external_id="sig-val-disagree")
        conn.execute(
            "UPDATE triage_items SET state=?, implement_job=?, validation_job=?, pr_url=? WHERE event_id=?",
            (triage.STATE_VALIDATING, "implement-job-004", "validation-job-004",
             "https://github.com/jkrumm/demo-repo/pull/10", eid),
        )
        conn.commit()
        _seed_implement_dispatch(conn, "implement-job-004")

        triage._hermes_cc_status = lambda job_id: {
            "ok": True, "status": "done",
            "verdict": {"summary": "the diff does not match the PR body. " + triage.VALIDATION_DISAGREE_MARKER},
        }
        merge_calls = []
        triage._run_hermes_cc_merge = lambda job_id: merge_calls.append(job_id) or None

        triage.poll_validation_jobs(conn, DEFAULT_POLICY, NOW, dry_run=False)

        assert merge_calls == [], "a disagreeing validation must never call merge"
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_MERGE_BLOCKED
        assert "disagree" in item["note"].lower()
        d = conn.execute("SELECT validation_status FROM dispatches WHERE job_id=?",
                         ("implement-job-004",)).fetchone()
        assert d["validation_status"] == "disagreed"


def test_confirmed_validation_merges_and_a_failed_deploy_check_still_lands_merged():
    with _triage_env() as (conn, ctx):
        eid = _seed_verdict_item(conn, external_id="sig-val-confirm")
        conn.execute(
            "UPDATE triage_items SET state=?, implement_job=?, validation_job=?, pr_url=? WHERE event_id=?",
            (triage.STATE_VALIDATING, "implement-job-005", "validation-job-005",
             "https://github.com/jkrumm/demo-repo/pull/11", eid),
        )
        conn.commit()
        _seed_implement_dispatch(conn, "implement-job-005")

        triage._hermes_cc_status = lambda job_id: {
            "ok": True, "status": "done",
            "verdict": {"summary": "looks right. " + triage.VALIDATION_CONFIRM_MARKER},
        }
        triage._run_hermes_cc_merge = lambda job_id: {
            "ok": True, "merged": True,
            "deploy": {"attempted": False, "reason": "autoDeploy is false for demo-repo"},
        }

        triage.poll_validation_jobs(conn, DEFAULT_POLICY, NOW, dry_run=False)

        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_MERGED
        assert "autoDeploy" in item["note"]
        d = conn.execute("SELECT validation_status FROM dispatches WHERE job_id=?",
                         ("implement-job-005",)).fetchone()
        assert d["validation_status"] == "confirmed"


def test_confirmed_merge_with_successful_deploy_enters_liveness_pending():
    with _triage_env() as (conn, ctx):
        eid = _seed_verdict_item(conn, external_id="sig-val-deploy")
        conn.execute(
            "UPDATE triage_items SET state=?, implement_job=?, validation_job=?, pr_url=? WHERE event_id=?",
            (triage.STATE_VALIDATING, "implement-job-006", "validation-job-006",
             "https://github.com/jkrumm/vps/pull/12", eid),
        )
        conn.commit()
        _seed_implement_dispatch(conn, "implement-job-006", repo="vps")

        triage._hermes_cc_status = lambda job_id: {
            "ok": True, "status": "done",
            "verdict": {"summary": "correct. " + triage.VALIDATION_CONFIRM_MARKER},
        }
        expected = [{"path": "observability/alerts/x.json", "name": "X", "threshold": 5, "thresholdType": "above"}]
        triage._run_hermes_cc_merge = lambda job_id: {
            "ok": True, "merged": True,
            "deploy": {"attempted": True, "ok": True, "key": "hyperdx-apply", "expectedAlerts": expected},
        }

        triage.poll_validation_jobs(conn, DEFAULT_POLICY, NOW, dry_run=False)

        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_LIVENESS_PENDING
        assert item["liveness_deadline"] is not None
        assert json.loads(item["deploy_expect_json"]) == expected


def test_liveness_confirmed_resolves_the_item():
    with _triage_env() as (conn, ctx):
        eid = _seed_verdict_item(conn, external_id="sig-live-ok")
        deadline = (NOW + dt.timedelta(hours=1)).isoformat()
        conn.execute(
            "UPDATE triage_items SET state=?, pr_url=?, liveness_deadline=?, deploy_expect_json=?, "
            "card_channel=?, card_ts=? WHERE event_id=?",
            (triage.STATE_LIVENESS_PENDING, "https://github.com/jkrumm/vps/pull/13", deadline,
             json.dumps([{"name": "X"}]), "C0TESTCHAN01", "1000.000009", eid),
        )
        conn.commit()

        policy = dict(DEFAULT_POLICY, repos={"demo-repo": {"liveness": "stub-live"}})
        triage.LIVENESS_ALLOWLIST["stub-live"] = lambda expected: (True, "matches live")

        triage.maybe_check_liveness(conn, policy, NOW, dry_run=False)

        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_RESOLVED
        assert item["note"].startswith(triage.LIVENESS_CONFIRMED_NOTE_PREFIX)
        assert len(ctx.updated) == 1 and len(ctx.posted) == 0


def test_liveness_failure_reopens_the_item_with_history():
    """The direct fix for the 61-re-triage scenario one level up the chain:
    an item that deployed but never verified live must not silently vanish
    OR silently sit "deployed" forever — past the window it REOPENS to
    `new`, carrying the PR link and the last liveness check on the card, so
    the next escalation does not start from zero."""
    with _triage_env() as (conn, ctx):
        eid = _seed_verdict_item(conn, external_id="sig-live-fail")
        past_deadline = (NOW - dt.timedelta(hours=1)).isoformat()
        conn.execute(
            "UPDATE triage_items SET state=?, pr_url=?, liveness_deadline=?, deploy_expect_json=?, "
            "card_channel=?, card_ts=? WHERE event_id=?",
            (triage.STATE_LIVENESS_PENDING, "https://github.com/jkrumm/vps/pull/14", past_deadline,
             json.dumps([{"name": "Y", "threshold": 5}]), "C0TESTCHAN01", "1000.000010", eid),
        )
        conn.commit()

        policy = dict(DEFAULT_POLICY, repos={"demo-repo": {"liveness": "stub-live-fail"}})
        triage.LIVENESS_ALLOWLIST["stub-live-fail"] = lambda expected: (False, "Y: live threshold=9 != expected 5")

        triage.maybe_check_liveness(conn, policy, NOW, dry_run=False)

        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_NEW, "must reopen to `new`, not sit deployed forever"
        assert "pull/14" in item["note"], "the reopened item must carry the PR in its history"
        assert "Y: live threshold=9" in item["note"], "the reopened item must carry the last liveness check"
        assert len(ctx.updated) == 1 and len(ctx.posted) == 0, (
            "the reopen must post its final update on the EXISTING card thread, never a new post")


def test_liveness_still_inside_window_neither_resolves_nor_reopens():
    with _triage_env() as (conn, ctx):
        eid = _seed_verdict_item(conn, external_id="sig-live-waiting")
        future_deadline = (NOW + dt.timedelta(hours=1)).isoformat()
        conn.execute(
            "UPDATE triage_items SET state=?, pr_url=?, liveness_deadline=?, deploy_expect_json=? "
            "WHERE event_id=?",
            (triage.STATE_LIVENESS_PENDING, "https://github.com/jkrumm/vps/pull/15", future_deadline,
             json.dumps([{"name": "Z"}]), eid),
        )
        conn.commit()

        policy = dict(DEFAULT_POLICY, repos={"demo-repo": {"liveness": "stub-live-waiting"}})
        triage.LIVENESS_ALLOWLIST["stub-live-waiting"] = lambda expected: (False, "not yet")

        triage.maybe_check_liveness(conn, policy, NOW, dry_run=False)

        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_LIVENESS_PENDING, "still inside the window — neither outcome yet"
        assert ctx.total_calls() == 0


# --- propose_mappings() — the one LLM call in this file ---------------------

def test_propose_candidates_age_reads_the_signature_not_the_row():
    """Age must come from the payload's ts_first, not events.first_seen.

    reconcile() rewrites first_seen every time it reopens a resolved row, so for a
    grouped source the two differ by months. Measured on the live DB:
    homelab-temperature-above-threshold carries ts_first = 2026-04-30 while
    first_seen reads 2026-09-04 — a 130-day-old recurring signature that looked
    five days old and sat under every age floor, permanently invisible to this
    pass. Regression test for that exact shape."""
    with _triage_env() as (conn, ctx):
        _insert_event(
            conn, source="slack_alert", external_id="reopened-old-sig",
            title="Recurring for months, row reopened two days ago",
            first_seen=NOW - dt.timedelta(days=2),
            payload={
                "first_text": "Recurring for months",
                "ts_first": str((NOW - dt.timedelta(days=130)).timestamp()),
                "ts_last": str(NOW.timestamp()),
            },
        )
        triage.ingest(conn, NOW)
        policy = {"proposeMappingsAgeDays": 7.0}

        sigs = {c["signature"] for c in triage._propose_mapping_candidates(conn, policy, NOW)}
        assert "slack_alert:reopened-old-sig" in sigs, (
            f"age must come from the payload's ts_first, not the reopened row's "
            f"first_seen — got {sigs}")


def test_propose_mappings_24h_cursor_prevents_second_run():
    with _triage_env() as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="cursor-sig", title="Cursor test",
                       first_seen=VERY_OLD)
        triage.ingest(conn, NOW)
        _init_policy_git_repo(ctx.tmp_dir, {"_readme": [], "rules": [], "ignore": []})
        policy = {"proposeMappingsAgeDays": 7.0}

        calls = {"n": 0}

        def _stub(_prompt):
            calls["n"] += 1
            return {"slack_alert:cursor-sig": {"action": "ignore", "reason": "test"}}

        triage._call_propose_mappings_model = _stub

        applied1 = triage.propose_mappings(conn, policy, NOW, dry_run=False)
        assert calls["n"] == 1
        assert len(applied1) == 1

        applied2 = triage.propose_mappings(conn, policy, NOW + dt.timedelta(hours=1), dry_run=False)
        assert calls["n"] == 1, "within 24h of the last run, the model must not be called again"
        assert applied2 == []

        applied3 = triage.propose_mappings(conn, policy, NOW + dt.timedelta(hours=25), dry_run=False)
        assert calls["n"] == 2, "past 24h, the next run must call the model again"
        assert len(applied3) == 1


def test_propose_mappings_age_threshold_excludes_young_signatures():
    with _triage_env() as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="young-sig", title="Too young",
                       first_seen=NOW - dt.timedelta(days=1))
        _insert_event(conn, source="slack_alert", external_id="old-sig", title="Old enough",
                       first_seen=VERY_OLD)
        triage.ingest(conn, NOW)
        policy = {"proposeMappingsAgeDays": 7.0}

        candidates = triage._propose_mapping_candidates(conn, policy, NOW)
        sigs = {c["signature"] for c in candidates}
        assert sigs == {"slack_alert:old-sig"}, (
            "a signature younger than proposeMappingsAgeDays must never be a candidate")


def test_propose_mappings_unparseable_response_is_non_fatal():
    with _triage_env() as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="bad-json-sig", title="Bad json",
                             first_seen=VERY_OLD)
        triage.ingest(conn, NOW)
        _init_policy_git_repo(ctx.tmp_dir, {"_readme": [], "rules": [], "ignore": []})
        policy = {"proposeMappingsAgeDays": 7.0}

        triage._resolve_openai_base_url = lambda: "https://example.test/v1"
        triage._resolve_openai_api_key = lambda: "test-key"

        class _FakeResp:
            def __init__(self, body: bytes):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        def _fake_urlopen(_req, timeout=None):
            body = json.dumps({"choices": [{"message": {"content": "not json at all {{{"}}]}).encode()
            return _FakeResp(body)

        saved_urlopen = triage.urllib.request.urlopen
        triage.urllib.request.urlopen = _fake_urlopen
        try:
            applied = triage.propose_mappings(conn, policy, NOW, dry_run=False)
        finally:
            triage.urllib.request.urlopen = saved_urlopen

        assert applied == [], "an unparseable model response must never raise or apply anything"
        item = triage._get_item(conn, eid)
        assert item["state"] == triage.STATE_NEW
        assert item["repo"] is None


def test_propose_mappings_drops_repo_that_does_not_resolve():
    with _triage_env() as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="maps-ok", title="Maps ok", first_seen=VERY_OLD)
        _insert_event(conn, source="slack_alert", external_id="maps-bad", title="Maps bad", first_seen=VERY_OLD)
        triage.ingest(conn, NOW)
        _setup_discoverable_repos(ctx, ["real-repo"])
        _init_policy_git_repo(ctx.tmp_dir, {"_readme": [], "rules": [], "ignore": []})
        policy = {"proposeMappingsAgeDays": 7.0}

        def _stub(_prompt):
            return {
                "slack_alert:maps-ok": {"action": "map", "repo": "real-repo", "reason": "matches"},
                "slack_alert:maps-bad": {"action": "map", "repo": "not-a-real-repo", "reason": "hallucinated"},
            }

        triage._call_propose_mappings_model = _stub

        applied = triage.propose_mappings(conn, policy, NOW, dry_run=False)
        applied_sigs = {a["signature"] for a in applied}
        assert applied_sigs == {"slack_alert:maps-ok"}, (
            "a repo that does not resolve under the dispatch root must be dropped, never applied")

        data = json.loads(triage.POLICY_PATH.read_text())
        matches = [r["match"] for r in data["rules"]]
        assert "slack_alert:maps-ok" in matches
        assert "slack_alert:maps-bad" not in matches


def test_propose_mappings_drops_denied_repo():
    with _triage_env() as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="maps-denied", title="Maps denied",
                       first_seen=VERY_OLD)
        triage.ingest(conn, NOW)
        _setup_discoverable_repos(ctx, ["denied-repo"], deny=["denied-repo"])
        _init_policy_git_repo(ctx.tmp_dir, {"_readme": [], "rules": [], "ignore": []})
        policy = {"proposeMappingsAgeDays": 7.0}

        triage._call_propose_mappings_model = lambda _prompt: {
            "slack_alert:maps-denied": {"action": "map", "repo": "denied-repo", "reason": "test"},
        }

        applied = triage.propose_mappings(conn, policy, NOW, dry_run=False)
        assert applied == [], "a denied repo must be dropped even if it resolves under root"


def test_propose_mappings_unsure_suppresses_reproposal_for_7_days():
    with _triage_env() as (conn, ctx):
        eid = _insert_event(conn, source="slack_alert", external_id="unsure-sig", title="Ambiguous",
                             first_seen=VERY_OLD)
        triage.ingest(conn, NOW)
        _init_policy_git_repo(ctx.tmp_dir, {"_readme": [], "rules": [], "ignore": []})
        policy = {"proposeMappingsAgeDays": 7.0}

        calls: list[str] = []
        triage._call_propose_mappings_model = lambda prompt: (
            calls.append(prompt) or {"slack_alert:unsure-sig": {"action": "unsure"}}
        )

        applied = triage.propose_mappings(conn, policy, NOW, dry_run=False)
        assert applied == []
        assert len(calls) == 1
        item = triage._get_item(conn, eid)
        assert item["propose_unsure_at"] is not None

        # 3 days later — still inside the cooldown.
        candidates = triage._propose_mapping_candidates(conn, policy, NOW + dt.timedelta(days=3))
        assert candidates == [], "an `unsure` signature must not be re-proposed within 7 days"

        # 8 days later — cooldown has expired.
        candidates = triage._propose_mapping_candidates(conn, policy, NOW + dt.timedelta(days=8))
        assert len(candidates) == 1 and candidates[0]["signature"] == "slack_alert:unsure-sig"


def test_propose_mappings_policy_round_trip_preserves_readme_and_key_order():
    with _triage_env() as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="round-trip-sig", title="Round trip",
                       first_seen=VERY_OLD)
        triage.ingest(conn, NOW)
        original = {
            "_readme": ["line one", "line two"],
            "cardChannel": "C0TESTCHAN01",
            "minOccurrences": 3,
            "minOpenMinutes": 30,
            "cooldownHours": 6,
            "quietResolveHours": 2,
            "ignoreUnstructuredSlackProse": True,
            "repos": {},
            "rules": [{"match": "slack_alert:existing-*", "repo": "existing-repo"}],
            "ignore": ["slack_alert:ignoreme-*"],
        }
        _init_policy_git_repo(ctx.tmp_dir, original)
        _setup_discoverable_repos(ctx, ["mapped-repo"])
        policy = {"proposeMappingsAgeDays": 7.0}

        triage._call_propose_mappings_model = lambda _prompt: {
            "slack_alert:round-trip-sig": {"action": "map", "repo": "mapped-repo", "reason": "matched"},
        }

        applied = triage.propose_mappings(conn, policy, NOW, dry_run=False)
        assert len(applied) == 1

        data = json.loads(triage.POLICY_PATH.read_text())
        assert list(data.keys()) == list(original.keys()), "top-level key order must survive"
        assert data["_readme"] == original["_readme"]
        assert len(data["rules"]) == 2
        new_rule = next(r for r in data["rules"] if r["match"] == "slack_alert:round-trip-sig")
        assert new_rule["repo"] == "mapped-repo"
        assert new_rule["proposedBy"] == "triage-auto"
        assert new_rule["reason"] == "matched"
        assert "proposedAt" in new_rule
        assert data["ignore"] == original["ignore"], "an unrelated section must round-trip untouched"


def test_propose_mappings_commit_skipped_when_policy_path_already_dirty():
    with _triage_env() as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="dirty-sig", title="Dirty path",
                       first_seen=VERY_OLD)
        triage.ingest(conn, NOW)
        repo_dir = _init_policy_git_repo(ctx.tmp_dir, {"_readme": [], "rules": [], "ignore": []})
        # An uncommitted edit already sitting in the working tree, simulating
        # a human's in-progress change to this exact file.
        triage.POLICY_PATH.write_text(triage.POLICY_PATH.read_text() + "\n// pending human edit\n")
        policy = {"proposeMappingsAgeDays": 7.0}

        triage._call_propose_mappings_model = lambda _prompt: {
            "slack_alert:dirty-sig": {"action": "ignore", "reason": "test"},
        }

        before_log = subprocess.run(["git", "-C", str(repo_dir), "log", "--oneline"],
                                     capture_output=True, text=True, check=True).stdout

        applied = triage.propose_mappings(conn, policy, NOW, dry_run=False)
        assert applied == [], "a dirty policy path must skip applying this run's proposals entirely"

        after_log = subprocess.run(["git", "-C", str(repo_dir), "log", "--oneline"],
                                    capture_output=True, text=True, check=True).stdout
        assert before_log == after_log, "no new commit must be created when the path is already dirty"

        status = subprocess.run(["git", "-C", str(repo_dir), "status", "--porcelain"],
                                 capture_output=True, text=True, check=True).stdout
        assert "triage-policy.json" in status, "the pre-existing dirty edit must remain, untouched by us"


def test_propose_mappings_dry_run_makes_zero_calls():
    with _triage_env() as (conn, ctx):
        _insert_event(conn, source="slack_alert", external_id="dry-run-sig", title="Dry run",
                       first_seen=VERY_OLD)
        triage.ingest(conn, NOW)
        _init_policy_git_repo(ctx.tmp_dir, {"_readme": [], "rules": [], "ignore": []})
        policy = {"proposeMappingsAgeDays": 7.0}

        calls = {"n": 0}
        triage._call_propose_mappings_model = lambda _prompt: calls.__setitem__("n", calls["n"] + 1) or {}

        applied = triage.propose_mappings(conn, policy, NOW, dry_run=True)
        assert applied == []
        assert calls["n"] == 0, "--dry-run must never call the model"


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
